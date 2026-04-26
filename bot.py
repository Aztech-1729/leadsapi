"""
LeadsAPI Admin Bot
Full inline button control panel:
  👥 Users    — list, add, pause, resume, edit limit, edit plan, delete
  🔑 API Keys — list, add, remove, set active Apify keys
  📊 Stats    — system-wide usage stats
  💾 Cache    — view cached queries, clear individual or all
  🌐 Tunnel   — view live tunnel URL
"""
import uuid
import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, ConversationHandler, filters
)

import config
from db import get_db
import keys as key_manager

# ── conversation states ───────────────────────────────────────────────────────
AWAIT_USER_LIMIT    = 1
AWAIT_USER_PLAN     = 2
AWAIT_EDIT_LIMIT    = 3
AWAIT_ADD_KEY       = 4
AWAIT_TEST_QUERY    = 5

PLANS = ["free", "basic", "pro", "unlimited"]
PLAN_LIMITS = {"free": 10, "basic": 25, "pro": 50, "unlimited": 100}

# ── guard ─────────────────────────────────────────────────────────────────────

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else (
            update.callback_query.from_user.id if update.callback_query else None
        )
        if uid != config.ADMIN_ID:
            return
        return await func(update, context)
    return wrapper


# ── keyboards ─────────────────────────────────────────────────────────────────

def main_menu_kb():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Users",    callback_data="menu_users_0"),
            InlineKeyboardButton("🔑 API Keys", callback_data="menu_keys"),
        ],
        [
            InlineKeyboardButton("📊 Stats",    callback_data="menu_stats"),
            InlineKeyboardButton("💾 Cache",    callback_data="menu_cache_0"),
        ],
        [
            InlineKeyboardButton("🌐 Tunnel",   callback_data="menu_tunnel"),
            InlineKeyboardButton("➕ Add User", callback_data="adduser_start"),
        ],
    ])


def back_kb(dest="menu_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data=dest)]])


# ── main menu ─────────────────────────────────────────────────────────────────

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛡 *LeadsAPI Admin Panel*\n\nFull control of your Lead Generation API.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )


async def menu_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "🛡 *LeadsAPI Admin Panel*\n\nFull control of your Lead Generation API.",
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )


# ── users list ────────────────────────────────────────────────────────────────

async def menu_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    page = int(q.data.split("_")[-1])
    db = get_db()
    page_size = 5
    skip = page * page_size
    total = await db.users.count_documents({})
    users = []
    async for u in db.users.find().skip(skip).limit(page_size):
        users.append(u)

    today = datetime.date.today().isoformat()
    text = f"👥 *Users* ({total} total) — Page {page + 1}\n\n"
    keyboard = []

    for u in users:
        status = "⏸" if u.get("paused") else "✅"
        used   = u.get("daily", {}).get(today, 0)
        limit  = u.get("daily_limit", 100)
        plan   = u.get("plan", "basic")
        short  = u["api_key"][:10] + "..."
        text  += f"{status} `{short}` — {used}/{limit} today — 📦 {plan}\n"
        keyboard.append([InlineKeyboardButton(
            f"{status} {short} [{plan}]",
            callback_data=f"user_detail_{u['api_key']}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"menu_users_{page - 1}"))
    if skip + page_size < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"menu_users_{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="menu_main")])

    await q.edit_message_text(text, parse_mode="Markdown",
                              reply_markup=InlineKeyboardMarkup(keyboard))


# ── user detail ───────────────────────────────────────────────────────────────

async def user_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("user_detail_", "")
    db = get_db()
    u = await db.users.find_one({"api_key": key})
    if not u:
        await q.edit_message_text("❌ User not found.", reply_markup=back_kb("menu_users_0"))
        return

    today  = datetime.date.today().isoformat()
    used   = u.get("daily", {}).get(today, 0)
    limit  = u.get("daily_limit", 100)
    plan   = u.get("plan", "basic")
    max_w  = PLAN_LIMITS.get(plan, 25)
    status = "⏸ Paused" if u.get("paused") else "✅ Active"
    created = u.get("created_at", "N/A")

    text = (
        f"👤 *User Details*\n\n"
        f"🔑 Key: `{key}`\n"
        f"Status: {status}\n"
        f"📦 Plan: *{plan}* (max {max_w} websites)\n"
        f"📅 Today: {used}/{limit}\n"
        f"📆 Monthly: {u.get('monthly_count', 0)}\n"
        f"📊 Total: {u.get('total_requests', 0)}\n"
        f"🗓 Created: {created}\n"
    )

    pause_btn = (
        InlineKeyboardButton("▶️ Resume", callback_data=f"user_resume_{key}")
        if u.get("paused") else
        InlineKeyboardButton("⏸ Pause",  callback_data=f"user_pause_{key}")
    )

    keyboard = [
        [pause_btn],
        [InlineKeyboardButton("✏️ Edit Daily Limit", callback_data=f"user_editlimit_{key}")],
        [InlineKeyboardButton("📦 Change Plan",      callback_data=f"user_plan_{key}")],
        [InlineKeyboardButton("🗑 Delete User",      callback_data=f"user_delete_confirm_{key}")],
        [InlineKeyboardButton("◀️ Back",             callback_data="menu_users_0")],
    ]
    await q.edit_message_text(text, parse_mode="Markdown",
                              reply_markup=InlineKeyboardMarkup(keyboard))


async def user_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    key = q.data.replace("user_pause_", "")
    db = get_db()
    await db.users.update_one({"api_key": key}, {"$set": {"paused": True}})
    await q.answer("⏸ Paused")
    q.data = f"user_detail_{key}"
    await user_detail(update, context)


async def user_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    key = q.data.replace("user_resume_", "")
    db = get_db()
    await db.users.update_one({"api_key": key}, {"$set": {"paused": False}})
    await q.answer("✅ Resumed")
    q.data = f"user_detail_{key}"
    await user_detail(update, context)


async def user_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("user_delete_confirm_", "")
    await q.edit_message_text(
        f"⚠️ *Delete user?*\n\n`{key}`\n\nThis cannot be undone.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, delete", callback_data=f"user_delete_do_{key}"),
            InlineKeyboardButton("❌ Cancel",      callback_data=f"user_detail_{key}")
        ]])
    )


async def user_delete_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("🗑 Deleted")
    key = q.data.replace("user_delete_do_", "")
    db = get_db()
    await db.users.delete_one({"api_key": key})
    await q.edit_message_text("✅ User deleted.", reply_markup=back_kb("menu_users_0"))


# ── change plan ───────────────────────────────────────────────────────────────

async def user_plan_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("user_plan_", "")
    db = get_db()
    u = await db.users.find_one({"api_key": key})
    current_plan = u.get("plan", "basic") if u else "basic"

    keyboard = []
    for plan in PLANS:
        mark = "✅ " if plan == current_plan else ""
        keyboard.append([InlineKeyboardButton(
            f"{mark}{plan.upper()} — {PLAN_LIMITS[plan]} websites",
            callback_data=f"user_setplan_{key}_{plan}"
        )])
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data=f"user_detail_{key}")])

    await q.edit_message_text(
        f"📦 *Change Plan*\n\nCurrent: *{current_plan}*\nSelect new plan:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def user_setplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    parts = q.data.replace("user_setplan_", "").rsplit("_", 1)
    key, plan = parts[0], parts[1]
    db = get_db()
    await db.users.update_one({"api_key": key}, {"$set": {"plan": plan}})
    await q.answer(f"✅ Plan set to {plan}")
    q.data = f"user_detail_{key}"
    await user_detail(update, context)


# ── edit daily limit ──────────────────────────────────────────────────────────

async def user_editlimit_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.replace("user_editlimit_", "")
    context.user_data["edit_limit_key"] = key
    await q.edit_message_text(
        f"✏️ Send the new *daily limit* for:\n`{key[:16]}...`",
        parse_mode="Markdown",
        reply_markup=back_kb(f"user_detail_{key}")
    )
    return AWAIT_EDIT_LIMIT


async def user_editlimit_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        new_limit = int(update.message.text.strip())
        assert new_limit > 0
    except (ValueError, AssertionError):
        await update.message.reply_text("❌ Send a valid positive integer:")
        return AWAIT_EDIT_LIMIT
    key = context.user_data.get("edit_limit_key")
    db = get_db()
    await db.users.update_one({"api_key": key}, {"$set": {"daily_limit": new_limit}})
    await update.message.reply_text(
        f"✅ Daily limit updated to *{new_limit}* for `{key[:10]}...`",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── add user ──────────────────────────────────────────────────────────────────

async def adduser_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    keyboard = []
    for plan in PLANS:
        keyboard.append([InlineKeyboardButton(
            f"{plan.upper()} — {PLAN_LIMITS[plan]} websites/req",
            callback_data=f"adduser_plan_{plan}"
        )])
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="menu_main")])
    await q.edit_message_text(
        "➕ *Add New User*\n\nSelect a plan:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def adduser_plan_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    plan = q.data.replace("adduser_plan_", "")
    context.user_data["new_user_plan"] = plan
    await q.edit_message_text(
        f"➕ Plan: *{plan.upper()}*\n\nSend the *daily request limit* (e.g. `100`):",
        parse_mode="Markdown",
        reply_markup=back_kb("adduser_start")
    )
    return AWAIT_USER_LIMIT


async def adduser_receive_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        limit = int(update.message.text.strip())
        assert limit > 0
    except (ValueError, AssertionError):
        await update.message.reply_text("❌ Invalid. Send a positive integer:")
        return AWAIT_USER_LIMIT

    plan    = context.user_data.get("new_user_plan", "basic")
    new_key = str(uuid.uuid4()).replace("-", "")
    db      = get_db()
    await db.users.insert_one({
        "api_key":       new_key,
        "plan":          plan,
        "daily_limit":   limit,
        "daily":         {},
        "monthly_count": 0,
        "total_requests":0,
        "paused":        False,
        "created_at":    datetime.datetime.utcnow().isoformat()
    })
    await update.message.reply_text(
        f"✅ *New user created!*\n\n"
        f"🔑 API Key:\n`{new_key}`\n\n"
        f"📦 Plan: *{plan}*\n"
        f"📅 Daily Limit: {limit}\n\n"
        f"_Share this key with your customer._",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── apify keys ────────────────────────────────────────────────────────────────

async def menu_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    all_keys = await key_manager.list_keys()
    text = "🔑 *Apify Keys*\n\n"
    keyboard = []

    if not all_keys:
        text += "_No keys configured yet._"
    for k in all_keys:
        mark = "🟢" if k["active"] else "⚪️"
        text += f"{mark} `{k['masked']}`\n"
        keyboard.append([InlineKeyboardButton(
            f"{'🟢 ' if k['active'] else ''}{k['masked']}",
            callback_data=f"key_detail_{k['index']}"
        )])

    keyboard.append([InlineKeyboardButton("➕ Add Key", callback_data="key_add_start")])
    keyboard.append([InlineKeyboardButton("◀️ Back",   callback_data="menu_main")])
    await q.edit_message_text(text, parse_mode="Markdown",
                              reply_markup=InlineKeyboardMarkup(keyboard))


async def key_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    idx      = int(q.data.replace("key_detail_", ""))
    all_keys = await key_manager.list_keys()
    if idx >= len(all_keys):
        await q.edit_message_text("❌ Key not found.", reply_markup=back_kb("menu_keys"))
        return
    k      = all_keys[idx]
    status = "🟢 Currently active" if k["active"] else "⚪️ Standby"
    text   = f"🔑 *Key #{idx + 1}*\n\nMasked: `{k['masked']}`\nStatus: {status}"
    keyboard = [
        [InlineKeyboardButton("🔄 Set Active", callback_data=f"key_setactive_{idx}")],
        [InlineKeyboardButton("🗑 Remove Key", callback_data=f"key_remove_{idx}")],
        [InlineKeyboardButton("◀️ Back",       callback_data="menu_keys")],
    ]
    await q.edit_message_text(text, parse_mode="Markdown",
                              reply_markup=InlineKeyboardMarkup(keyboard))


async def key_setactive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    idx = int(q.data.replace("key_setactive_", ""))
    db  = get_db()
    await db.config.update_one(
        {"type": "apify_keys"},
        {"$set": {"current_index": idx}}
    )
    await q.answer(f"✅ Key #{idx + 1} set as active", show_alert=True)
    q.data = "menu_keys"
    await menu_keys(update, context)


async def key_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q        = update.callback_query
    await q.answer()
    idx      = int(q.data.replace("key_remove_", ""))
    all_keys = await key_manager.list_keys()
    if idx >= len(all_keys):
        await q.edit_message_text("❌ Key not found.", reply_markup=back_kb("menu_keys"))
        return
    remaining = await key_manager.remove_key(all_keys[idx]["full"])
    await q.edit_message_text(
        f"✅ Key removed. {remaining} key(s) remaining.",
        reply_markup=back_kb("menu_keys")
    )


async def key_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "➕ *Add Apify Key*\n\nSend the full Apify API key:",
        parse_mode="Markdown",
        reply_markup=back_kb("menu_keys")
    )
    return AWAIT_ADD_KEY


async def key_add_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw   = update.message.text.strip()
    total = await key_manager.add_key(raw)
    await update.message.reply_text(
        f"✅ Key added! Total keys: *{total}*",
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# ── stats ─────────────────────────────────────────────────────────────────────

async def menu_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    db    = get_db()
    today = datetime.date.today().isoformat()

    total_users  = await db.users.count_documents({})
    paused_users = await db.users.count_documents({"paused": True})
    all_keys     = await key_manager.list_keys()
    cached_count = await db.leads_cache.count_documents({})

    # Today's requests
    daily_total = 0
    async for u in db.users.find({}, {"daily": 1}):
        daily_total += u.get("daily", {}).get(today, 0)

    # All-time aggregate
    pipeline = [{"$group": {"_id": None,
                             "total":   {"$sum": "$total_requests"},
                             "monthly": {"$sum": "$monthly_count"}}}]
    agg        = await db.users.aggregate(pipeline).to_list(1)
    total_req  = agg[0]["total"]   if agg else 0
    monthly_req= agg[0]["monthly"] if agg else 0

    # Plan breakdown
    plan_counts = {}
    for plan in PLANS:
        plan_counts[plan] = await db.users.count_documents({"plan": plan})

    plan_text = " | ".join(f"{p}: {plan_counts[p]}" for p in PLANS)

    text = (
        "📊 *LeadsAPI Stats*\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"⏸ Paused: `{paused_users}`\n"
        f"✅ Active: `{total_users - paused_users}`\n\n"
        f"📦 Plans: `{plan_text}`\n\n"
        f"📅 Requests Today: `{daily_total}`\n"
        f"📆 This Month: `{monthly_req}`\n"
        f"📊 All-Time: `{total_req}`\n\n"
        f"🔑 Apify Keys: `{len(all_keys)}`\n"
        f"💾 Cached Queries: `{cached_count}`\n"
    )
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb("menu_main"))


# ── cache management ──────────────────────────────────────────────────────────

async def menu_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    page      = int(q.data.split("_")[-1])
    db        = get_db()
    page_size = 5
    skip      = page * page_size
    total     = await db.leads_cache.count_documents({})
    entries   = []
    async for doc in db.leads_cache.find({}, {"query": 1, "count": 1, "created_at": 1}).skip(skip).limit(page_size):
        entries.append(doc)

    text     = f"💾 *Cache* ({total} queries)\n\n"
    keyboard = []

    for doc in entries:
        q_text   = doc.get("query", "?")[:30]
        count    = doc.get("count", 0)
        created  = doc.get("created_at")
        age_hrs  = ""
        if created:
            age = (datetime.datetime.utcnow() - created).total_seconds() / 3600
            age_hrs = f" {age:.0f}h ago"
        text += f"🔍 `{q_text}` — {count} leads{age_hrs}\n"
        keyboard.append([InlineKeyboardButton(
            f"🗑 {q_text[:25]}",
            callback_data=f"cache_del_{doc.get('query','')[:40]}"
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"menu_cache_{page - 1}"))
    if skip + page_size < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"menu_cache_{page + 1}"))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🗑 Clear ALL Cache", callback_data="cache_clear_all_confirm")])
    keyboard.append([InlineKeyboardButton("◀️ Back", callback_data="menu_main")])

    await q.edit_message_text(text, parse_mode="Markdown",
                              reply_markup=InlineKeyboardMarkup(keyboard))


async def cache_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q         = update.callback_query
    await q.answer()
    query_key = q.data.replace("cache_del_", "")
    db        = get_db()
    await db.leads_cache.delete_one({"query": query_key})
    await q.answer("🗑 Cache entry deleted", show_alert=True)
    q.data = "menu_cache_0"
    await menu_cache(update, context)


async def cache_clear_all_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "⚠️ *Clear ALL cached queries?*\n\nNext requests will re-scrape everything.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes, clear all", callback_data="cache_clear_all_do"),
            InlineKeyboardButton("❌ Cancel",         callback_data="menu_cache_0")
        ]])
    )


async def cache_clear_all_do(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q  = update.callback_query
    db = get_db()
    result = await db.leads_cache.delete_many({})
    await q.answer(f"✅ {result.deleted_count} entries cleared", show_alert=True)
    await q.edit_message_text(
        f"✅ Cleared *{result.deleted_count}* cached queries.",
        parse_mode="Markdown",
        reply_markup=back_kb("menu_main")
    )


# ── tunnel ────────────────────────────────────────────────────────────────────

async def menu_tunnel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q  = update.callback_query
    await q.answer()
    db = get_db()
    doc = await db.config.find_one({"name": "leads_tunnel"})
    url = doc.get("url", "Not available yet") if doc else "Not running"
    text = (
        f"🌐 *Cloudflare Tunnel*\n\n"
        f"URL: `{url}`\n\n"
        f"_Restart the server to get a fresh URL._\n\n"
        f"*Test endpoint:*\n"
        f"`GET {url}/leads?query=gyms+in+hyderabad`\n"
        f"Header: `x-api-key: YOUR_KEY`"
    )
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=back_kb("menu_main"))


# ── cancel ─────────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_kb())
    return ConversationHandler.END


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(config.BOT_TOKEN).build()

    # Add user conversation
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(adduser_start, pattern="^adduser_start$")],
        states={
            AWAIT_USER_LIMIT: [
                CallbackQueryHandler(adduser_plan_selected, pattern="^adduser_plan_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, adduser_receive_limit)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    ))

    # Edit limit conversation
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(user_editlimit_start, pattern="^user_editlimit_")],
        states={
            AWAIT_EDIT_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, user_editlimit_receive)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    ))

    # Add key conversation
    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(key_add_start, pattern="^key_add_start$")],
        states={
            AWAIT_ADD_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, key_add_receive)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False
    ))

    # Navigation handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_main,    pattern="^menu_main$"))
    app.add_handler(CallbackQueryHandler(menu_users,   pattern=r"^menu_users_\d+$"))
    app.add_handler(CallbackQueryHandler(menu_keys,    pattern="^menu_keys$"))
    app.add_handler(CallbackQueryHandler(menu_stats,   pattern="^menu_stats$"))
    app.add_handler(CallbackQueryHandler(menu_cache,   pattern=r"^menu_cache_\d+$"))
    app.add_handler(CallbackQueryHandler(menu_tunnel,  pattern="^menu_tunnel$"))

    # User actions
    app.add_handler(CallbackQueryHandler(user_detail,         pattern="^user_detail_"))
    app.add_handler(CallbackQueryHandler(user_pause,          pattern="^user_pause_"))
    app.add_handler(CallbackQueryHandler(user_resume,         pattern="^user_resume_"))
    app.add_handler(CallbackQueryHandler(user_delete_confirm, pattern="^user_delete_confirm_"))
    app.add_handler(CallbackQueryHandler(user_delete_do,      pattern="^user_delete_do_"))
    app.add_handler(CallbackQueryHandler(user_plan_menu,      pattern="^user_plan_"))
    app.add_handler(CallbackQueryHandler(user_setplan,        pattern="^user_setplan_"))

    # Key actions
    app.add_handler(CallbackQueryHandler(key_detail,    pattern=r"^key_detail_\d+$"))
    app.add_handler(CallbackQueryHandler(key_setactive, pattern=r"^key_setactive_\d+$"))
    app.add_handler(CallbackQueryHandler(key_remove,    pattern=r"^key_remove_\d+$"))

    # Cache actions
    app.add_handler(CallbackQueryHandler(cache_delete,           pattern="^cache_del_"))
    app.add_handler(CallbackQueryHandler(cache_clear_all_confirm,pattern="^cache_clear_all_confirm$"))
    app.add_handler(CallbackQueryHandler(cache_clear_all_do,     pattern="^cache_clear_all_do$"))

    print("🤖 LeadsAPI Bot started. Polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
