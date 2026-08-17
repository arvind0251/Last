import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ChatJoinRequestHandler,
    CallbackQueryHandler, ContextTypes,
)
from telegram.error import TelegramError
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
import database as db
import payment_server as pay

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != config.OWNER_ID:
            await update.effective_message.reply_text("⛔ Ye command sirf owner use kar sakta hai.")
            return
        return await func(update, context)
    return wrapper


# ---------------- OWNER: GROUP MANAGEMENT ----------------

@owner_only
async def cmd_addgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group ke andar bhejo: /addgroup"""
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.effective_message.reply_text("Ye command group ke andar bhejo, jaha bot admin ho.")
        return
    try:
        link = await context.bot.create_chat_invite_link(chat.id, creates_join_request=True, name="subscription-link")
    except TelegramError as e:
        await update.effective_message.reply_text(f"Link nahi ban paya: {e}\nBot ko 'Invite Users' admin permission do.")
        return

    db.add_group(chat.id, chat.title, link.invite_link, update.effective_user.id)
    await update.effective_message.reply_text(
        f"✅ Group register ho gaya!\n\nGroup ID: `{chat.id}`\nInvite Link (approval-required):\n{link.invite_link}\n\n"
        f"Ab is group ke liye /addplan aur /grant use kar sakte ho.",
        parse_mode="Markdown",
    )


@owner_only
async def cmd_listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    groups = db.list_groups()
    if not groups:
        await update.effective_message.reply_text("Koi group register nahi hai. /addgroup use karo group ke andar.")
        return
    text = "📋 *Registered Groups*\n\n"
    for g in groups:
        text += f"• `{g['group_id']}` — {g['title']}\n  {g['invite_link']}\n\n"
    await update.effective_message.reply_text(text, parse_mode="Markdown")


# ---------------- OWNER: PLANS ----------------

@owner_only
async def cmd_addplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/addplan <group_id> <days> <amount> <label...>"""
    args = context.args
    if len(args) < 4:
        await update.effective_message.reply_text("Usage: /addplan <group_id> <days> <amount> <label>")
        return
    group_id, days, amount = int(args[0]), int(args[1]), float(args[2])
    label = " ".join(args[3:])
    db.add_plan(group_id, label, days, amount)
    await update.effective_message.reply_text(f"✅ Plan add ho gaya: {label} — {days} din — ₹{amount}")


@owner_only
async def cmd_listplans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    plans = db.list_plans()
    if not plans:
        await update.effective_message.reply_text("Koi plan nahi hai.")
        return
    text = "💳 *Plans*\n\n"
    for p in plans:
        text += f"#{p['id']} — group `{p['group_id']}` — {p['label']} — {p['days']}din — ₹{p['amount']}\n"
    await update.effective_message.reply_text(text, parse_mode="Markdown")


# ---------------- OWNER: MANUAL GRANT / EXTEND / REVOKE ----------------

@owner_only
async def cmd_grant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/grant <user_id> <group_id> <days>"""
    args = context.args
    if len(args) < 3:
        await update.effective_message.reply_text("Usage: /grant <user_id> <group_id> <days>")
        return
    user_id, group_id, days = int(args[0]), int(args[1]), int(args[2])
    group = db.get_group(group_id)
    if not group:
        await update.effective_message.reply_text("Ye group register nahi hai. Pehle /addgroup karo.")
        return
    db.create_pending_subscription(user_id, group_id, days)
    await update.effective_message.reply_text(
        f"✅ User `{user_id}` ko `{days}` din ke liye access mil gaya.\n\n"
        f"Ye link user ko bhejo (join request bhejte hi auto-approve ho jayega):\n{group['invite_link']}",
        parse_mode="Markdown",
    )


@owner_only
async def cmd_extend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/extend <user_id> <group_id> <extra_days>"""
    args = context.args
    if len(args) < 3:
        await update.effective_message.reply_text("Usage: /extend <user_id> <group_id> <extra_days>")
        return
    user_id, group_id, extra_days = int(args[0]), int(args[1]), int(args[2])
    new_end = db.extend_subscription(user_id, group_id, extra_days)
    if new_end:
        await update.effective_message.reply_text(f"✅ Extend ho gaya. Nayi expiry: {new_end}")
    else:
        await update.effective_message.reply_text("Is user ki active subscription nahi mili.")


@owner_only
async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/revoke <user_id> <group_id>"""
    args = context.args
    if len(args) < 2:
        await update.effective_message.reply_text("Usage: /revoke <user_id> <group_id>")
        return
    user_id, group_id = int(args[0]), int(args[1])
    db.revoke_subscription(user_id, group_id)
    await _ban_and_unban(context, group_id, user_id)
    await update.effective_message.reply_text("✅ User remove/ban kar diya gaya.")


@owner_only
async def cmd_listsubs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    group_id = int(args[0]) if args else None
    subs = db.list_subscriptions(group_id=group_id)
    if not subs:
        await update.effective_message.reply_text("Koi subscription nahi mili.")
        return
    text = "🧾 *Subscriptions*\n\n"
    for s in subs[:50]:
        text += (f"#{s['id']} user `{s['user_id']}` group `{s['group_id']}` "
                  f"status:{s['status']} end:{s.get('end_date')}\n")
    await update.effective_message.reply_text(text, parse_mode="Markdown")


# ---------------- ADMIN PANEL ----------------

@owner_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("📋 Groups", callback_data="adm_groups"),
         InlineKeyboardButton("💳 Plans", callback_data="adm_plans")],
        [InlineKeyboardButton("🧾 Active Subs", callback_data="adm_subs_active"),
         InlineKeyboardButton("⏳ Pending Subs", callback_data="adm_subs_pending")],
    ]
    await update.effective_message.reply_text("🛠 *Admin Panel*", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id != config.OWNER_ID:
        await q.answer("Sirf owner ke liye.", show_alert=True)
        return
    await q.answer()
    if q.data == "adm_groups":
        groups = db.list_groups()
        text = "📋 *Groups*\n\n" + "\n".join(f"`{g['group_id']}` {g['title']}" for g in groups) if groups else "Koi group nahi."
    elif q.data == "adm_plans":
        plans = db.list_plans()
        text = "💳 *Plans*\n\n" + "\n".join(f"#{p['id']} {p['label']} ₹{p['amount']}/{p['days']}d" for p in plans) if plans else "Koi plan nahi."
    elif q.data == "adm_subs_active":
        subs = db.list_subscriptions(status="active")
        text = "🧾 *Active*\n\n" + "\n".join(f"user `{s['user_id']}` grp `{s['group_id']}` end:{s['end_date']}" for s in subs) if subs else "Koi active nahi."
    elif q.data == "adm_subs_pending":
        subs = db.list_subscriptions(status="pending")
        text = "⏳ *Pending (join ka wait)*\n\n" + "\n".join(f"user `{s['user_id']}` grp `{s['group_id']}`" for s in subs) if subs else "Koi pending nahi."
    else:
        text = "?"
    await q.edit_message_text(text, parse_mode="Markdown")


# ---------------- USER: /buy (3rd Party Payment) ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Namaste! 👋\n\n"
        "Subscription lene ke liye /buy likhiye.\n"
        "Kisi bhi group me join karne ke liye pehle subscription lena zaroori hai.\n\n"
        "📌 *Available Commands:*\n"
        "/start - Bot start karein\n"
        "/buy - Subscription lein\n"
        "/help - Madad lein",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📖 *Help Menu*\n\n"
        "*User Commands:*\n"
        "/start - Bot start karein\n"
        "/buy - Subscription lein (QR payment)\n\n"
        "*Owner Commands:*\n"
        "/addgroup - Group register karein (group me bhejein)\n"
        "/listgroups - Registered groups dikhayein\n"
        "/addplan - Plan add karein\n"
        "/listplans - Plans dikhayein\n"
        "/grant - Manual access dein\n"
        "/extend - Subscription extend karein\n"
        "/revoke - User ban karein\n"
        "/listsubs - Subscriptions dikhayein\n"
        "/admin - Admin panel\n\n"
        "💳 *Payment:* 3rd Party UPI QR se payment hoti hai.",
        parse_mode="Markdown"
    )


async def cmd_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """3rd Party Payment — Group select"""
    groups = db.list_groups_with_plans()
    if not groups:
        await update.effective_message.reply_text("❌ Abhi koi group available nahi hai.")
        return
    kb = [[InlineKeyboardButton(f"📌 {g['title']}", callback_data=f"buygrp_{g['group_id']}")] for g in groups]
    await update.effective_message.reply_text(
        "💳 *Group chuniye:*\n\n"
        "Jis group me join karna hai, usko select karein.",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


async def group_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Group choose -> Plans dikhao"""
    q = update.callback_query
    await q.answer()
    group_id = int(q.data.split("_")[1])
    group = db.get_group(group_id)
    plans = db.list_plans(group_id=group_id)
    if not plans:
        await q.edit_message_text("❌ Is group ke liye abhi koi plan nahi hai.")
        return
    kb = [[InlineKeyboardButton(f"📆 {p['label']} — ₹{p['amount']} / {p['days']} din", 
                                callback_data=f"buy_{p['id']}")]
          for p in plans]
    kb.append([InlineKeyboardButton("⬅️ Wapas", callback_data="buy_back")])
    await q.edit_message_text(
        f"📌 *{group['title']}*\n\n"
        f"Apna plan chuniye:",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


async def buy_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Wapas groups list"""
    q = update.callback_query
    await q.answer()
    groups = db.list_groups_with_plans()
    kb = [[InlineKeyboardButton(f"📌 {g['title']}", callback_data=f"buygrp_{g['group_id']}")] for g in groups]
    await q.edit_message_text(
        "💳 *Group chuniye:*",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )


async def buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """3rd Party QR generate"""
    q = update.callback_query
    await q.answer("⏳ QR generate ho raha...")
    
    plan_id = int(q.data.split("_")[1])
    plan = db.get_plan(plan_id)
    if not plan:
        await q.edit_message_text("❌ Plan nahi mila.")
        return
    
    # 3rd party QR
    result = pay.create_qr_third_party(plan["amount"], q.from_user.id)
    
    if result["status"] != "success":
        await q.edit_message_text(f"❌ QR generate nahi ho paaya: {result.get('error', 'Unknown error')}")
        return
    
    order_id = result["order_id"]
    db.create_payment(order_id, q.from_user.id, plan["group_id"], plan_id, plan["amount"], plan["days"])
    
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Paid — Check Payment", callback_data=f"check_{order_id}")
    ]])
    
    await context.bot.send_photo(
        q.from_user.id,
        result["qr_url"],
        caption=f"💳 *₹{plan['amount']} — {plan['label']}*\n\n"
                f"📌 Group: *{db.get_group(plan['group_id'])['title']}*\n\n"
                f"QR code scan karein aur payment karein.\n"
                f"Payment ke baad neeche *'✅ Paid — Check Payment'* button dabayein.\n\n"
                f"⏳ Payment verify hote hi aapko join link mil jayega.",
        reply_markup=kb,
        parse_mode="Markdown"
    )
    await q.edit_message_text("✅ QR code neeche bhej diya gaya.")


async def check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """3rd Party payment check"""
    q = update.callback_query
    await q.answer("⏳ Checking payment status...")
    
    order_id = q.data.split("_")[1]
    payment = db.get_payment(order_id)
    
    if not payment:
        await context.bot.send_message(q.from_user.id, "❌ Order nahi mila. /buy se dobara try karein.")
        return
    
    if payment["status"] == "success":
        await context.bot.send_message(q.from_user.id, "✅ Ye payment pehle hi confirm ho chuki hai.")
        group = db.get_group(payment["group_id"])
        await context.bot.send_message(
            q.from_user.id,
            f"🔗 Join link: {group['invite_link']}\n\n"
            f"Link par tap karein aur 'Request to Join' bhejein — turant approve ho jayega.",
            parse_mode="Markdown"
        )
        return
    
    result = pay.verify_payment_third_party(order_id)
    
    if result["status"] == "success":
        # Payment success
        db.update_payment_status(order_id, "success")
        db.create_pending_subscription(
            payment["user_id"], 
            payment["group_id"], 
            payment["days"],
            order_id=order_id, 
            amount=payment["amount"]
        )
        group = db.get_group(payment["group_id"])
        
        await context.bot.send_message(
            q.from_user.id,
            f"✅ *Payment Successful!* 🎉\n\n"
            f"📌 Group: *{group['title']}*\n"
            f"🔗 Join link: {group['invite_link']}\n\n"
            f"*Steps to join:*\n"
            f"1️⃣ Link par tap karein\n"
            f"2️⃣ 'Request to Join' bhejein\n"
            f"3️⃣ Turant approve ho jayega\n\n"
            f"✅ Subscription active ho jayegi!",
            parse_mode="Markdown"
        )
        await q.edit_message_text("✅ Payment confirmed! Join link upar bhej diya gaya.")
    else:
        await context.bot.send_message(
            q.from_user.id, 
            "❌ Payment nahi mili.\n\n"
            "Kuch der baad dobara try karein.\n"
            "Agar payment kar diya hai toh thoda wait karein aur dobara button dabayein."
        )


# ---------------- JOIN REQUEST HANDLING ----------------

async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    user_id = req.from_user.id
    group_id = req.chat.id

    sub = db.get_pending_subscription(user_id, group_id)
    if sub:
        try:
            await context.bot.approve_chat_join_request(group_id, user_id)
        except TelegramError as e:
            log.warning(f"approve failed: {e}")
            return
        start, end = db.activate_subscription(sub["id"], sub["plan_days"])
        try:
            await context.bot.send_message(
                user_id,
                f"✅ *Subscription Activated!* 🎉\n\n"
                f"📌 Group: *{req.chat.title}*\n"
                f"📅 Valid till: `{end.strftime('%d-%b-%Y %H:%M UTC')}`\n\n"
                f"Enjoy! 🚀",
                parse_mode="Markdown"
            )
        except TelegramError:
            pass
    else:
        try:
            await context.bot.decline_chat_join_request(group_id, user_id)
            await context.bot.send_message(
                user_id, 
                "❌ Aapke paas is group ki valid subscription nahi hai.\n\n"
                "Subscription lene ke liye /buy karein.\n"
                "Payment ke baad dobara join request bhejein."
            )
        except TelegramError:
            pass


# ---------------- EXPIRY BAN ----------------

async def _ban_and_unban(context_or_app, group_id, user_id):
    bot = context_or_app.bot if hasattr(context_or_app, "bot") else context_or_app
    try:
        await bot.ban_chat_member(group_id, user_id)
        await bot.unban_chat_member(group_id, user_id, only_if_banned=True)
        try:
            await bot.send_message(
                user_id, 
                "⏰ *Subscription Expired!*\n\n"
                "Aapki subscription expire ho gayi hai aur aapko group se remove kar diya gaya hai.\n\n"
                "Renew karne ke liye /buy karein."
            )
        except TelegramError:
            pass
    except TelegramError as e:
        log.warning(f"ban failed for {user_id} in {group_id}: {e}")


async def check_expired_job(application):
    expired = db.get_expired_subscriptions()
    for s in expired:
        await _ban_and_unban(application, s["group_id"], s["user_id"])
        db.mark_expired(s["id"])
        log.info(f"Expired & removed user {s['user_id']} from group {s['group_id']}")


def setup_scheduler(application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_expired_job, "interval", minutes=config.CHECK_INTERVAL_MINUTES, args=[application])
    scheduler.start()
    return scheduler


# ---------------- BUILD APPLICATION ----------------

def build_application():
    application = Application.builder().token(config.BOT_TOKEN).build()

    # User commands
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("buy", cmd_buy))

    # Owner commands
    application.add_handler(CommandHandler("addgroup", cmd_addgroup))
    application.add_handler(CommandHandler("listgroups", cmd_listgroups))
    application.add_handler(CommandHandler("addplan", cmd_addplan))
    application.add_handler(CommandHandler("listplans", cmd_listplans))
    application.add_handler(CommandHandler("grant", cmd_grant))
    application.add_handler(CommandHandler("extend", cmd_extend))
    application.add_handler(CommandHandler("revoke", cmd_revoke))
    application.add_handler(CommandHandler("listsubs", cmd_listsubs))
    application.add_handler(CommandHandler("admin", cmd_admin))

    # Callbacks
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^adm_"))
    application.add_handler(CallbackQueryHandler(group_select_callback, pattern="^buygrp_"))
    application.add_handler(CallbackQueryHandler(buy_back_callback, pattern="^buy_back$"))
    application.add_handler(CallbackQueryHandler(buy_callback, pattern="^buy_\\d+$"))
    application.add_handler(CallbackQueryHandler(check_callback, pattern="^check_"))

    # Join request
    application.add_handler(ChatJoinRequestHandler(handle_join_request))

    return application
