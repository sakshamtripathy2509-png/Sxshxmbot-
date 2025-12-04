# ultra_auto_forward_premium_bot.py

import logging
import datetime
import asyncio
from collections import defaultdict

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# ================== CONFIG ==================

BOT_TOKEN = "8520987601:AAGWkbohRMWUSqZNclG7qC_VYLU0z8IpqYk"   # <-- put your bot token here
OWNER_ID = 1945796348               # <-- put YOUR numeric Telegram ID here

# Forwarding settings
FORWARD_ONLY = "all"               # "all", "text", "media"
ADD_FOOTER = True
FOOTER_TEXT = "\n\n🔁 Forwarded via Auto Forward Bot"

# Per-plan delays (seconds)
FREE_DELAY = 1.0        # default for free users (you asked for 1 sec)
BASIC_DELAY = 0.5       # Basic premium
SUPER_DELAY = 0.0       # Super premium
OWNER_DELAY = 0.0       # Owner always instant

# Logging setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== RUNTIME STATE ==================

bot_start_time = datetime.datetime.now()

# owner + admins
admin_ids = set([OWNER_ID])   # multi-admin system, owner included

# in-memory data
SOURCE_CHANNELS = set()       # channel IDs to forward FROM
TARGET_GROUPS = set()         # group IDs to forward TO (auto-detected)

premium_users = {}            # {user_id: {"plan": str, "expires": datetime}}
forwarded_ids = set()         # to avoid duplicates

forwarding_enabled = True

# analytics / stats
total_forwarded = 0
today_forwarded = 0
today_date = datetime.date.today()

# filters
allow_keywords = set()        # messages must contain one of these (if not empty)
block_keywords = set()        # messages must NOT contain any of these

# settings
quiet_mode = False            # if True: bot won't say hello in groups
log_forwarding_to_owner = False  # if True: send simple log to owner

# per-group settings (future expansion)
group_settings = defaultdict(
    lambda: {
        "enabled": True,
        "mode": "all",          # "all", "text", "media" (currently global FORWARD_ONLY used)
        "footer": True,
        "clean_caption": False,
    }
)

# per-user language (placeholder for now – only 'en')
user_language = defaultdict(lambda: "en")

# mapping: which user added the bot to which group
group_owner = {}  # {group_id: user_id}


# ================== HELPERS ==================

def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_admin(user_id: int) -> bool:
    return user_id in admin_ids


def is_premium(user_id: int) -> bool:
    if is_owner(user_id):
        return True
    data = premium_users.get(user_id)
    if not data:
        return False
    return data["expires"] > datetime.datetime.now()


def human_timedelta(dt: datetime.datetime) -> str:
    delta = datetime.datetime.now() - dt
    secs = int(delta.total_seconds())
    days, secs = divmod(secs, 86400)
    hours, secs = divmod(secs, 3600)
    mins, secs = divmod(secs, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def clean_caption(text: str) -> str:
    if not text:
        return text

    import re
    text = re.sub(r"@\w+", "", text)          # remove @username
    text = re.sub(r"http\S+", "", text)       # remove URLs
    text = re.sub(r"\s+", " ", text).strip()  # normalize spaces
    return text


def text_matches_filters(text: str) -> bool:
    if not text:
        text = ""
    lowered = text.lower()

    # blocklist: reject if any blocked word in message
    for bad in block_keywords:
        if bad.lower() in lowered:
            return False

    # allowlist: if non-empty, require at least one match
    if allow_keywords:
        for good in allow_keywords:
            if good.lower() in lowered:
                break
        else:
            return False

    return True


def bump_forward_stats():
    global total_forwarded, today_forwarded, today_date
    total_forwarded += 1
    now_date = datetime.date.today()
    if now_date != today_date:
        today_date = now_date
        today_forwarded = 0
    today_forwarded += 1


def build_main_menu(user_id: int):
    text = (
        "🚀 *Ultra Auto Post Forwarding Bot*\n"
        "Forwards posts from source channels to all groups where the bot is added.\n\n"
        "Use the menu below 👇"
    )

    keyboard = [
        [
            InlineKeyboardButton("📡 Sources", callback_data="menu_sources"),
            InlineKeyboardButton("🎯 Groups", callback_data="menu_groups"),
        ],
        [
            InlineKeyboardButton("📨 Forwarding", callback_data="menu_forward"),
            InlineKeyboardButton("💳 Premium", callback_data="menu_premium"),
        ],
        [
            InlineKeyboardButton("📊 Analytics", callback_data="menu_analytics"),
            InlineKeyboardButton("👤 My Profile", callback_data="menu_profile"),
        ],
        [
            InlineKeyboardButton("⚙ Settings", callback_data="menu_settings"),
            InlineKeyboardButton("👤 Owner Info", callback_data="menu_ownerinfo"),
        ],
    ]

    if is_owner(user_id):
        keyboard.append(
            [InlineKeyboardButton("👑 Owner Panel", callback_data="menu_owner")]
        )

    return text, keyboard


# ================== COMMAND HANDLERS ==================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text, keyboard = build_main_menu(user_id)
    await update.effective_chat.send_message(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "ON" if forwarding_enabled else "PAUSED"
    await update.message.reply_text(
        f"📊 Forwarding status: *{status}*",
        parse_mode="Markdown",
    )


async def alive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = human_timedelta(bot_start_time)
    text = (
        "🟢 *Bot Alive*\n\n"
        f"⏱ Uptime: `{uptime}`\n"
        f"📡 Source Channels: `{len(SOURCE_CHANNELS)}`\n"
        f"🎯 Groups: `{len(TARGET_GROUPS)}`\n"
        f"💬 Forwarded Today: `{today_forwarded}`\n"
        f"👤 Owner: `@SxShxM_Op`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------- Source channels ----------

async def addsource_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        channel_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text(
            "Use: `/addsource <channel_id>`",
            parse_mode="Markdown",
        )

    SOURCE_CHANNELS.add(channel_id)
    await update.message.reply_text(
        f"✅ Source channel added:\n`{channel_id}`",
        parse_mode="Markdown",
    )

    if not is_owner(update.effective_user.id):
        try:
            await context.bot.send_message(
                OWNER_ID,
                f"📡 *New Source Added by User*\n"
                f"User ID: `{update.effective_user.id}`\n"
                f"Channel ID: `{channel_id}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Notify owner failed: {e}")


async def removesource_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Only admin/owner can remove sources.")

    try:
        channel_id = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text(
            "Use: `/removesource <channel_id>`",
            parse_mode="Markdown",
        )

    if channel_id in SOURCE_CHANNELS:
        SOURCE_CHANNELS.remove(channel_id)
        await update.message.reply_text(
            f"🗑 Source channel removed:\n`{channel_id}`",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("⚠ That channel is not in the source list.")


async def sources_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not SOURCE_CHANNELS:
        return await update.message.reply_text("📭 No source channels added yet.")
    text = "📡 *Active Source Channels:*\n\n"
    for ch in SOURCE_CHANNELS:
        text += f"• `{ch}`\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------- Groups (auto detected) ----------

async def listgroups_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not TARGET_GROUPS:
        return await update.message.reply_text("📭 Bot is not in any group yet.")

    text = "🎯 *Groups where bot is active:*\n\n"
    for g in TARGET_GROUPS:
        owner_id_of_group = group_owner.get(g)
        label = "Free"
        if owner_id_of_group:
            if is_owner(owner_id_of_group):
                label = "Owner (Instant)"
            elif owner_id_of_group in premium_users:
                plan = premium_users[owner_id_of_group]["plan"].lower()
                if plan == "basic":
                    label = "Basic Premium (0.5s)"
                elif plan == "super":
                    label = "Super Premium (Instant)"
        text += f"• `{g}` – {label}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ---------- Premium system ----------

async def buy_basic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💠 *Basic Premium – $10/month*\n\n"
        "Features:\n"
        "• Unlimited forwarding\n"
        "• Keyword filtering\n"
        "• Custom footer\n"
        "• Faster group forwarding\n\n"
        "📩 *To Purchase:*\n"
        "Telegram: @SxShxM_Op\n"
        "UPI: `Saksham.1412@fam`\n\n"
        "Owner will activate your plan manually."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def buy_super_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "💎 *Super Premium – $25/month*\n\n"
        "Features:\n"
        "• All Basic features\n"
        "• Instant group forwarding\n"
        "• Caption cleaner (optional)\n"
        "• Advanced filters\n\n"
        "📩 *To Purchase:*\n"
        "Telegram: @SxShxM_Op\n"
        "UPI: `Saksham.1412@fam`\n\n"
        "Owner will activate your plan manually."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Only owner can grant premium.")

    try:
        target_user = int(context.args[0])
        plan = context.args[1].lower()
        days = int(context.args[2])
    except (IndexError, ValueError):
        return await update.message.reply_text(
            "Use:\n`/grant <user_id> <plan> <days>`\n\n"
            "Example:\n`/grant 123456789 basic 30`",
            parse_mode="Markdown",
        )

    expire = datetime.datetime.now() + datetime.timedelta(days=days)
    premium_users[target_user] = {"plan": plan, "expires": expire}

    await update.message.reply_text(
        f"✅ Premium granted!\n\n"
        f"User: `{target_user}`\n"
        f"Plan: *{plan}*\n"
        f"Expires: `{expire}`",
        parse_mode="Markdown",
    )


# ---------- Forward control ----------

async def pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global forwarding_enabled
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Only admin/owner can pause forwarding.")
    forwarding_enabled = False
    await update.message.reply_text("⏸ Forwarding paused.")


async def resume_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global forwarding_enabled
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Only admin/owner can resume forwarding.")
    forwarding_enabled = True
    await update.message.reply_text("▶ Forwarding resumed.")


# ---------- Broadcast ----------

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Only owner can broadcast.")
    if not context.args:
        return await update.message.reply_text(
            "Use: `/broadcast <message>`",
            parse_mode="Markdown",
        )
    msg = " ".join(context.args)
    count = 0
    for uid in list(premium_users.keys()):
        try:
            await context.bot.send_message(uid, f"📢 Broadcast:\n{msg}")
            count += 1
        except Exception:
            continue
    await update.message.reply_text(f"📨 Broadcast sent to {count} premium user(s).")


# ---------- Filters & settings ----------

async def add_allow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Only admin/owner can edit filters.")
    if not context.args:
        return await update.message.reply_text("Use: `/addallow word`")
    word = " ".join(context.args).strip()
    allow_keywords.add(word)
    await update.message.reply_text(f"✅ Added to allowlist: `{word}`", parse_mode="Markdown")


async def add_block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Only admin/owner can edit filters.")
    if not context.args:
        return await update.message.reply_text("Use: `/addblock word`")
    word = " ".join(context.args).strip()
    block_keywords.add(word)
    await update.message.reply_text(f"✅ Added to blocklist: `{word}`", parse_mode="Markdown")


async def clear_filters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Only admin/owner can edit filters.")
    allow_keywords.clear()
    block_keywords.clear()
    await update.message.reply_text("🧹 All filters cleared.")


async def quietmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global quiet_mode
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("❌ Only admin/owner can set quiet mode.")
    if not context.args:
        return await update.message.reply_text("Use: `/quietmode on|off`")
    val = context.args[0].lower()
    if val not in ["on", "off"]:
        return await update.message.reply_text("Use: `/quietmode on|off`")
    quiet_mode = (val == "on")
    await update.message.reply_text(f"🔇 Quiet mode: *{val}*", parse_mode="Markdown")


async def log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global log_forwarding_to_owner
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Only owner can toggle logs.")
    if not context.args:
        return await update.message.reply_text("Use: `/log on|off`")
    val = context.args[0].lower()
    if val not in ["on", "off"]:
        return await update.message.reply_text("Use: `/log on|off`")
    log_forwarding_to_owner = (val == "on")
    await update.message.reply_text(f"📥 Forward log: *{val}*", parse_mode="Markdown")


async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Available languages: `en` (default)\nUse: `/language en` for now.",
            parse_mode="Markdown",
        )
    lang = context.args[0].lower()
    if lang != "en":
        return await update.message.reply_text(
            "Currently only `en` is supported.",
            parse_mode="Markdown",
        )
    user_language[update.effective_user.id] = lang
    await update.message.reply_text("🌐 Language set to English.")


# ---------- Admin management ----------

async def addadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Only owner can add admins.")
    try:
        uid = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("Use: `/addadmin <user_id>`")
    admin_ids.add(uid)
    await update.message.reply_text(f"✅ Added admin: `{uid}`", parse_mode="Markdown")


async def removeadmin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return await update.message.reply_text("❌ Only owner can remove admins.")
    try:
        uid = int(context.args[0])
    except (IndexError, ValueError):
        return await update.message.reply_text("Use: `/removeadmin <user_id>`")
    if uid == OWNER_ID:
        return await update.message.reply_text("❌ Cannot remove owner.")
    if uid in admin_ids:
        admin_ids.remove(uid)
        await update.message.reply_text(f"🗑 Removed admin: `{uid}`", parse_mode="Markdown")
    else:
        await update.message.reply_text("⚠ That user is not an admin.")


async def admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "👨‍💻 *Admins:*\n\n"
    for uid in admin_ids:
        mark = " (Owner)" if uid == OWNER_ID else ""
        text += f"• `{uid}`{mark}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


# ---------- Stats ----------

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = human_timedelta(bot_start_time)
    text = (
        "📊 *Bot Statistics*\n\n"
        f"⏱ Uptime: `{uptime}`\n"
        f"📡 Sources: `{len(SOURCE_CHANNELS)}`\n"
        f"🎯 Groups: `{len(TARGET_GROUPS)}`\n"
        f"💬 Forwarded today: `{today_forwarded}`\n"
        f"📨 Forwarded total: `{total_forwarded}`\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ================== INLINE MENU (ULTRA MULTI-PAGE) ==================

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    # MAIN MENU
    if data == "main_menu":
        text, keyboard = build_main_menu(user_id)
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- SOURCE MENU ----------
    if data == "menu_sources":
        text = (
            "📡 *Source Channels*\n\n"
            "Channels where the bot reads posts and forwards them to groups.\n"
            "Add channels using `/addsource <channel_id>`."
        )
        keyboard = [
            [InlineKeyboardButton("📋 View Sources", callback_data="btn_listsources")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "btn_listsources":
        if not SOURCE_CHANNELS:
            text = "📭 No source channels added yet."
        else:
            text = "📡 *Active Sources:*\n\n"
            for ch in SOURCE_CHANNELS:
                text += f"• `{ch}`\n"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_sources")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- GROUPS MENU ----------
    if data == "menu_groups":
        text = (
            f"🎯 *Target Groups*\n\n"
            f"Bot is active in *{len(TARGET_GROUPS)}* group(s).\n"
            "Any group where the bot is added will receive forwarded posts.\n"
            "Forward speed depends on who added the bot:\n"
            "• Free user → ~1s delay\n"
            "• Basic premium → ~0.5s delay\n"
            "• Super premium / Owner → instant\n"
        )
        keyboard = [
            [InlineKeyboardButton("📋 View Groups", callback_data="btn_listgroups")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "btn_listgroups":
        if not TARGET_GROUPS:
            text = "📭 Bot is not in any group yet."
        else:
            text = "🎯 *Groups where bot is active:*\n\n"
            for g in TARGET_GROUPS:
                owner_id_of_group = group_owner.get(g)
                label = "Free (1s)"
                if owner_id_of_group:
                    if is_owner(owner_id_of_group):
                        label = "Owner (Instant)"
                    elif owner_id_of_group in premium_users:
                        plan = premium_users[owner_id_of_group]["plan"].lower()
                        if plan == "basic":
                            label = "Basic Premium (0.5s)"
                        elif plan == "super":
                            label = "Super Premium (Instant)"
                text += f"• `{g}` – {label}\n"
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_groups")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- FORWARD MENU ----------
    if data == "menu_forward":
        text = (
            "📨 *Forwarding Controls*\n\n"
            "• Pause/Resume forwarding\n"
            "• Use filters (/addallow, /addblock)\n"
            "• Speed is automatically based on premium level."
        )
        keyboard = [
            [InlineKeyboardButton("⏸ Pause", callback_data="btn_pause")],
            [InlineKeyboardButton("▶ Resume", callback_data="btn_resume")],
            [InlineKeyboardButton("🧩 Filter Info", callback_data="btn_filterinfo")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "btn_pause":
        if not is_admin(user_id):
            return await query.edit_message_text("❌ Only admin/owner can pause.", parse_mode="Markdown")
        global forwarding_enabled
        forwarding_enabled = False
        text = "⏸ Forwarding paused."
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_forward")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "btn_resume":
        if not is_admin(user_id):
            return await query.edit_message_text("❌ Only admin/owner can resume.", parse_mode="Markdown")
        forwarding_enabled = True
        text = "▶ Forwarding resumed."
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_forward")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "btn_filterinfo":
        text = (
            "🧩 *Filter Settings*\n\n"
            "`/addallow word` – forward only messages containing this word (if allowlist not empty)\n"
            "`/addblock word` – NEVER forward messages containing this word\n"
            "`/clearfilters` – remove all filters\n"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_forward")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- PREMIUM MENU ----------
    if data == "menu_premium":
        text = (
            "💳 *Premium Plans*\n\n"
            "Click a plan to see details.\n"
        )
        keyboard = [
            [InlineKeyboardButton("💠 Basic", callback_data="prem_basic")],
            [InlineKeyboardButton("💎 Super", callback_data="prem_super")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "prem_basic":
        text = (
            "💠 *Basic Premium – $10/month*\n\n"
            "• Unlimited forwarding\n"
            "• Custom footer\n"
            "• Basic filters\n"
            "• Group delay: ~0.5s\n\n"
            "Contact: @SxShxM_Op\nUPI: `Saksham.1412@fam`"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_premium")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "prem_super":
        text = (
            "💎 *Super Premium – $25/month*\n\n"
            "• All Basic features\n"
            "• Instant group forwarding\n"
            "• Caption cleaner\n\n"
            "Contact: @SxShxM_Op\nUPI: `Saksham.1412@fam`"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_premium")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- ANALYTICS MENU ----------
    if data == "menu_analytics":
        uptime = human_timedelta(bot_start_time)
        text = (
            "📊 *Analytics Overview*\n\n"
            f"⏱ Uptime: `{uptime}`\n"
            f"📡 Sources: `{len(SOURCE_CHANNELS)}`\n"
            f"🎯 Groups: `{len(TARGET_GROUPS)}`\n"
            f"💬 Today: `{today_forwarded}`\n"
            f"📨 Total: `{total_forwarded}`\n"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- PROFILE MENU ----------
    if data == "menu_profile":
        prem = is_premium(user_id)
        prem_text = "Yes" if prem else "No"
        plan = premium_users.get(user_id, {}).get("plan", "-")
        expires = premium_users.get(user_id, {}).get("expires", "-")
        text = (
            "👤 *My Profile*\n\n"
            f"🆔 User ID: `{user_id}`\n"
            f"💎 Premium: `{prem_text}`\n"
            f"📦 Plan: `{plan}`\n"
            f"⏳ Expires: `{expires}`\n"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- SETTINGS MENU ----------
    if data == "menu_settings":
        text = (
            "⚙ *Settings*\n\n"
            "• Language: `/language en`\n"
            "• Quiet mode: `/quietmode on|off`\n"
            "• Forward log to owner: `/log on|off`\n"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- OWNER INFO ----------
    if data == "menu_ownerinfo":
        text = (
            "👤 *Bot Owner*\n\n"
            "• Username: @SxShxM_Op\n"
            "• Role: Bot creator & manager\n\n"
            "Contact owner only for help or premium activation."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    # ---------- OWNER PANEL ----------
    if data == "menu_owner":
        if not is_owner(user_id):
            return await query.edit_message_text("❌ You are not the owner.")
        text = (
            "👑 *Owner Panel*\n\n"
            "Use commands or tools here:\n"
            "• Grant premium\n"
            "• Manage admins\n"
            "• Broadcast\n"
            "• View stats\n"
        )
        keyboard = [
            [InlineKeyboardButton("🎁 Grant Premium", callback_data="owner_grantpremium")],
            [InlineKeyboardButton("👨‍💻 Admins", callback_data="owner_admins")],
            [InlineKeyboardButton("📢 Broadcast", callback_data="owner_broadcastinfo")],
            [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
        ]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "owner_grantpremium":
        if not is_owner(user_id):
            return await query.edit_message_text("❌ You are not the owner.")
        text = (
            "🎁 *Grant Premium*\n\n"
            "Use:\n`/grant <user_id> <plan> <days>`\n\n"
            "Examples:\n"
            "`/grant 123456789 basic 30`\n"
            "`/grant 123456789 super 60`"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_owner")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "owner_admins":
        if not is_owner(user_id):
            return await query.edit_message_text("❌ You are not the owner.")
        text = (
            "👨‍💻 *Admin Management*\n\n"
            "`/addadmin <user_id>`\n"
            "`/removeadmin <user_id>`\n"
            "`/admins` – list admins\n"
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_owner")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    if data == "owner_broadcastinfo":
        if not is_owner(user_id):
            return await query.edit_message_text("❌ You are not the owner.")
        text = (
            "📢 *Broadcast Info*\n\n"
            "Use:\n`/broadcast <message>`\n\n"
            "Message will be sent to all premium users."
        )
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="menu_owner")]]
        return await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


# ================== AUTO GROUP JOIN / LEAVE ==================

async def bot_joined_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    new_members = update.message.new_chat_members

    if chat.type not in ["group", "supergroup"]:
        return

    for member in new_members:
        if member.id == context.bot.id:
            # save who added the bot
            group_owner[chat.id] = user.id

            TARGET_GROUPS.add(chat.id)

            if not quiet_mode:
                await context.bot.send_message(
                    chat.id,
                    f"👋 **Hello everyone!**\n"
                    f"I am now active in *{chat.title}*.\n\n"
                    f"⭐ Premium groups get faster forwarding.\n"
                    f"⚪ Free groups: ~1 second delay.",
                    parse_mode="Markdown",
                )

            try:
                await context.bot.send_message(
                    OWNER_ID,
                    "🎯 *Bot Added to New Group*\n\n"
                    f"🏷 Name: `{chat.title}`\n"
                    f"🆔 ID: `{chat.id}`\n"
                    f"👤 Added by: `{user.id}`",
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.warning(f"Owner notify failed: {e}")


async def bot_left_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    member = update.message.left_chat_member

    if member and member.id == context.bot.id:
        if chat.id in TARGET_GROUPS:
            TARGET_GROUPS.remove(chat.id)
        group_owner.pop(chat.id, None)

        try:
            await context.bot.send_message(
                OWNER_ID,
                "❌ *Bot Removed From Group*\n\n"
                f"🏷 Name: `{chat.title}`\n"
                f"🆔 ID: `{chat.id}`",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning(f"Owner notify failed: {e}")


# ================== FORWARDING HANDLER ==================

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global total_forwarded

    msg = update.message
    if msg is None:
        return

    chat_id = update.effective_chat.id

    # Only from source channels
    if chat_id not in SOURCE_CHANNELS:
        return

    if not forwarding_enabled:
        return

    # duplicate protection
    if msg.message_id in forwarded_ids:
        return
    forwarded_ids.add(msg.message_id)

    # detect if media
    is_media = bool(
        msg.photo
        or msg.video
        or msg.document
        or msg.audio
        or msg.animation
        or msg.voice
        or msg.sticker
    )

    # global mode filter
    if FORWARD_ONLY == "text" and not msg.text:
        return
    if FORWARD_ONLY == "media" and not is_media:
        return

    # text/caption for filters
    text_for_filter = msg.text or msg.caption or ""
    if not text_matches_filters(text_for_filter):
        return

    # forward to all target groups
    if not TARGET_GROUPS:
        return

    for target in list(TARGET_GROUPS):
        gs = group_settings[target]
        if not gs["enabled"]:
            continue

        # ------- ADVANCED SPEED PER GROUP -------
        owner_id_of_group = group_owner.get(target)
        delay = FREE_DELAY  # default for free

        if owner_id_of_group:
            if is_owner(owner_id_of_group):
                delay = OWNER_DELAY
            elif owner_id_of_group in premium_users:
                plan = premium_users[owner_id_of_group]["plan"].lower()
                if plan == "basic":
                    delay = BASIC_DELAY
                elif plan == "super":
                    delay = SUPER_DELAY

        try:
            # TEXT MESSAGE
            if msg.text:
                send_text = msg.text
                if gs["clean_caption"]:
                    send_text = clean_caption(send_text)
                if gs["footer"] and ADD_FOOTER:
                    send_text += FOOTER_TEXT
                await context.bot.send_message(target, send_text)

            # MEDIA WITH CAPTION
            elif msg.caption and (msg.photo or msg.video or msg.document):
                caption = msg.caption
                if gs["clean_caption"]:
                    caption = clean_caption(caption)
                if gs["footer"] and ADD_FOOTER:
                    caption = (caption or "") + FOOTER_TEXT
                await msg.copy(chat_id=target, caption=caption)

            # OTHER MEDIA/STICKER/VOICE
            else:
                await msg.copy(chat_id=target)

            bump_forward_stats()

            if log_forwarding_to_owner:
                try:
                    await context.bot.send_message(
                        OWNER_ID,
                        f"📨 Forwarded from `{chat_id}` to `{target}`",
                        parse_mode="Markdown",
                    )
                except Exception:
                    pass

            if delay > 0:
                await asyncio.sleep(delay)

        except Exception as e:
            logger.warning(f"Failed to forward to {target}: {e}")


# ================== MAIN ==================

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("alive", alive_cmd))

    app.add_handler(CommandHandler("addsource", addsource_cmd))
    app.add_handler(CommandHandler("removesource", removesource_cmd))
    app.add_handler(CommandHandler("sources", sources_cmd))

    app.add_handler(CommandHandler("listgroups", listgroups_cmd))

    app.add_handler(CommandHandler("buy_basic", buy_basic_cmd))
    app.add_handler(CommandHandler("buy_super", buy_super_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))

    app.add_handler(CommandHandler("pause", pause_cmd))
    app.add_handler(CommandHandler("resume", resume_cmd))

    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    app.add_handler(CommandHandler("addallow", add_allow_cmd))
    app.add_handler(CommandHandler("addblock", add_block_cmd))
    app.add_handler(CommandHandler("clearfilters", clear_filters_cmd))

    app.add_handler(CommandHandler("quietmode", quietmode_cmd))
    app.add_handler(CommandHandler("log", log_cmd))
    app.add_handler(CommandHandler("language", language_cmd))

    app.add_handler(CommandHandler("addadmin", addadmin_cmd))
    app.add_handler(CommandHandler("removeadmin", removeadmin_cmd))
    app.add_handler(CommandHandler("admins", admins_cmd))

    app.add_handler(CommandHandler("stats", stats_cmd))

    # Inline menu
    app.add_handler(CallbackQueryHandler(menu_callback))

    # Auto join/leave group
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, bot_joined_group))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, bot_left_group))

    # Forwarding
    app.add_handler(MessageHandler(filters.ALL, forward_message))

    logger.info("BOT IS RUNNING...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())