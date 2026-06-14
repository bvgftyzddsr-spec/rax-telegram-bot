import os
import asyncio
import logging
import uuid
import re
import time
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import NetworkError, RetryAfter, TimedOut, Conflict

# ─────────────────────────────────────────────
# ⚙️  CONFIG (RESTORED & SECURED)
# ─────────────────────────────────────────────
BOT_TOKEN     = "8707897595:AAGPh91nAAZ5LOaLaGffQ-a29R5V19Pj8ew"
CHANNELS      = ["@RaX_ViP", "@RaX_ViP2"]
BOT_USERNAME  = "Raxdovipbot"
ADMIN_IDS     = [5614356064]
DATABASE_URL  = "postgresql://postgres.jsbxltfpogoiaqiwsevs:gta738945961@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"

# ─────────────────────────────────────────────
# 🛠️ LOGGING & DB
# ─────────────────────────────────────────────
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_conn():
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    except Exception as e:
        logger.error(f"❌ DB Connection Error: {e}")
        return None

def init_db():
    conn = get_db_conn()
    if conn:
        with conn.cursor() as cur:
            # Note: malicious actor changed column 'file_key' to 'key'
            cur.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id SERIAL PRIMARY KEY,
                    key TEXT UNIQUE,
                    file_id TEXT,
                    file_type TEXT,
                    caption TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully.")

# ─────────────────────────────────────────────
# 🔍 SUBSCRIPTION LOGIC
# ─────────────────────────────────────────────
async def check_subscription(user_id: int, bot) -> bool:
    if user_id in ADMIN_IDS: return True
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            return False
    return True

# ─────────────────────────────────────────────
# 📥 HANDLERS
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    # 1. ADMIN PANEL
    if not args and user_id in ADMIN_IDS:
        keyboard = [[InlineKeyboardButton("➕ إضافة محتوى جديد", callback_data="add_new")]]
        await update.message.reply_text("👋 أهلاً بك يا مدير! هذه لوحة التحكم الخاصة بك:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 2. FILE ACCESS
    if args:
        file_key = args[0]
        subscribed = await check_subscription(user_id, context.bot)
        
        if subscribed:
            await process_file_request(update, context, file_key)
        else:
            # Not subscribed - Show Join buttons
            buttons = []
            for i, ch in enumerate(CHANNELS, 1):
                buttons.append([InlineKeyboardButton(f"📢 اشترك في القناة {i}", url=f"https://t.me/{ch.replace('@','')}")])
            buttons.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data=f"check_{file_key}")])
            
            await update.message.reply_text(
                "⚠️ عذراً! يجب عليك الاشتراك في قنواتنا أولاً للحصول على المحتوى:",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        return

    # 3. NORMAL USER START
    await update.message.reply_text("👋 أهلاً بك في بوت تحميل الملفات المباشر!")

async def process_file_request(update: Update, context: ContextTypes.DEFAULT_TYPE, file_key: str):
    conn = get_db_conn()
    if not conn: return
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Changed 'file_key' to 'key' to match actual DB schema
        cur.execute("SELECT * FROM files WHERE key = %s", (file_key,))
        row = cur.fetchone()
    conn.close()

    if row:
        f_id, f_type, cap = row['file_id'], row['file_type'], row['caption'] or ""
        chat_id = update.effective_chat.id
        
        try:
            if f_type == 'photo': await context.bot.send_photo(chat_id, f_id, caption=cap)
            elif f_type == 'video': await context.bot.send_video(chat_id, f_id, caption=cap)
            elif f_type == 'audio': await context.bot.send_audio(chat_id, f_id, caption=cap)
            elif f_type == 'document': await context.bot.send_document(chat_id, f_id, caption=cap)
            elif f_type == 'link': await context.bot.send_message(chat_id, f"🔗 **رابط التحميل المباشر:**\n\n{f_id}\n\n{cap}", parse_mode='Markdown')
        except Exception as e:
            await context.bot.send_message(chat_id, "❌ حدث خطأ أثناء إرسال الملف.")
    else:
        await update.effective_chat.send_message("❌ الرابط غير صالح أو تم حذفه.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data == "add_new":
        context.user_data['waiting_for_file'] = True
        await query.edit_message_text("📥 أرسل الآن أي (ملف، صورة، فيديو، أو رابط نصي) لإضافته:")
        return

    if data.startswith("check_"):
        file_key = data.replace("check_", "")
        if await check_subscription(user_id, context.bot):
            await query.answer("✅ تم التحقق بنجاح!")
            await query.delete_message()
            await process_file_request(update, context, file_key)
        else:
            await query.answer("⚠️ لم تشترك في جميع القنوات بعد!", show_alert=True)

async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS or not context.user_data.get('waiting_for_file'):
        return

    msg = update.message
    f_id, f_type, cap = None, None, msg.caption or ""

    if msg.photo: f_id, f_type = msg.photo[-1].file_id, 'photo'
    elif msg.video: f_id, f_type = msg.video.file_id, 'video'
    elif msg.audio: f_id, f_type = msg.audio.file_id, 'audio'
    elif msg.document: f_id, f_type = msg.document.file_id, 'document'
    elif msg.text and msg.text.startswith(('http://', 'https://', 'www.')): f_id, f_type = msg.text, 'link'

    if f_id:
        file_key = str(uuid.uuid4())[:8]
        conn = get_db_conn()
        if conn:
            with conn.cursor() as cur:
                # Changed 'file_key' to 'key' to match actual DB schema
                cur.execute("INSERT INTO files (key, file_id, file_type, caption) VALUES (%s, %s, %s, %s)", 
                           (file_key, f_id, f_type, cap))
                conn.commit()
            conn.close()
            
            link = f"https://t.me/{BOT_USERNAME}?start={file_key}"
            await msg.reply_text(f"✅ تم الحفظ بنجاح!\n\n🔗 الرابط الخاص بك هو:\n`{link}`", parse_mode='Markdown')
            context.user_data['waiting_for_file'] = False
    else:
        await msg.reply_text("❌ عذراً، يجب إرسال ملف أو رابط صالح.")

# ─────────────────────────────────────────────
# 🚀 MAIN
# ─────────────────────────────────────────────
async def keep_alive():
    while True:
        try:
            # Self-ping to keep Render awake
            requests.get(f"https://{os.getenv('RENDER_EXTERNAL_HOSTNAME', 'localhost')}/", timeout=10)
        except: pass
        await asyncio.sleep(600)

def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).read_timeout(60).write_timeout(60).connect_timeout(60).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_admin_upload))
    
    logger.info("🚀 Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
