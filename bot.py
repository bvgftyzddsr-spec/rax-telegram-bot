import os
import asyncio
import logging
import uuid
import re
import time
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

# ─────────────────────────────────────────────
# ⚙️  CONFIG (STABLE & SECURE)
# ─────────────────────────────────────────────
BOT_TOKEN     = "8707897595:AAGPh91nAAZ5LOaLaGffQ-a29R5V19Pj8ew"
CHANNELS      = ["@RaX_ViP", "@RaX_ViP2"]
BOT_USERNAME  = "Raxdovipbot"
ADMIN_IDS     = [5614356064]
DATABASE_URL  = "postgresql://postgres.jsbxltfpogoiaqiwsevs:gta738945961@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?sslmode=require"
RENDER_URL    = os.environ.get("RENDER_EXTERNAL_URL", "https://rax-telegram-bot.onrender.com")

# ─────────────────────────────────────────────
# 🛠️ LOGGING & STABILITY
# ─────────────────────────────────────────────
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_conn():
    for _ in range(3):
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require', connect_timeout=10)
            return conn
        except Exception as e:
            logger.error(f"⚠️ DB Connection Retry: {e}")
            time.sleep(1)
    return None

def init_db():
    conn = get_db_conn()
    if conn:
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'files'")
            if not cur.fetchone():
                cur.execute("""
                    CREATE TABLE files (
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
        logger.info("✅ Database check complete.")

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
    logger.info(f"👤 Received /start from {user_id} with args: {args}")

    if not args and user_id in ADMIN_IDS:
        keyboard = [
            [InlineKeyboardButton("➕ إضافة محتوى جديد", callback_data="add_new")],
            [InlineKeyboardButton("📋 قائمة المحتويات", callback_data="list_content")],
            [InlineKeyboardButton("📊 إحصائيات القاعدة", callback_data="db_stats")]
        ]
        await update.message.reply_text("👋 أهلاً بك يا مدير! هذه لوحة التحكم الخاصة بك:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if args:
        file_key = args[0].strip()
        # EVERYONE sees the interaction buttons first now
        buttons = []
        for i, ch in enumerate(CHANNELS, 1):
            buttons.append([InlineKeyboardButton(f"📢 اشترك في القناة {i}", url=f"https://t.me/{ch.replace('@','')}")])
        
        # Interaction Row
        interaction_row = [
            InlineKeyboardButton("🔥 تفاعل", url=f"https://t.me/{CHANNELS[0].replace('@','')}"),
            InlineKeyboardButton("❤️ تفاعل", url=f"https://t.me/{CHANNELS[0].replace('@','')}"),
            InlineKeyboardButton("💯 تفاعل", url=f"https://t.me/{CHANNELS[0].replace('@','')}")
        ]
        buttons.append(interaction_row)
        buttons.append([InlineKeyboardButton("📥 استلام الملف الآن ✅", callback_data=f"check_{file_key}")])
        
        await update.message.reply_text(
            "🚀 **خطوة أخيرة للحصول على ملفك:**\n\n"
            "🔹 اشترك في القنوات أعلاه.\n"
            "🔹 تفاعل مع آخر منشور (🔥 ❤️ 💯).\n"
            "🔹 ثم اضغط على الزر أدناه لاستلام ملفك فوراً.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode='Markdown'
        )
        return

    await update.message.reply_text("👋 أهلاً بك في بوت تحميل الملفات المباشر!")

async def process_file_request(update: Update, context: ContextTypes.DEFAULT_TYPE, file_key: str):
    logger.info(f"🔍 Searching for key: {file_key}")
    conn = get_db_conn()
    if not conn: return
    
    row = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'files'")
            cols = [c['column_name'] for c in cur.fetchall()]
            search_cols = [col for col in cols if col in ['key', 'file_key']]
            for col in search_cols:
                cur.execute(f"SELECT * FROM files WHERE LOWER({col}) = LOWER(%s)", (file_key,))
                row = cur.fetchone()
                if row: break
    except Exception as e:
        logger.error(f"❌ DB Query Error: {e}")
    finally:
        conn.close()

    if row:
        f_id, f_type, cap = row['file_id'], row['file_type'], row['caption'] or ""
        chat_id = update.effective_chat.id
        logger.info(f"✅ Found {f_type}. Sending to {chat_id}...")
        try:
            if f_type == 'photo': await context.bot.send_photo(chat_id, f_id, caption=cap)
            elif f_type == 'video': await context.bot.send_video(chat_id, f_id, caption=cap)
            elif f_type == 'audio': await context.bot.send_audio(chat_id, f_id, caption=cap)
            elif f_type == 'document': await context.bot.send_document(chat_id, f_id, caption=cap)
            elif f_type == 'link': await context.bot.send_message(chat_id, f"🔗 **رابط التحميل المباشر:**\n\n{f_id}\n\n{cap}", parse_mode='Markdown')
        except Exception as e:
            logger.error(f"❌ Send Error: {e}")
            await context.bot.send_message(chat_id, "❌ حدث خطأ أثناء إرسال الملف.")
    else:
        logger.warning(f"❌ Key NOT found: {file_key}")
        await update.effective_chat.send_message("❌ الرابط غير صالح أو تم حذفه.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    logger.info(f"🖱️ Callback from {user_id}: {data}")
    
    # ⚡ QUICK FIX: Always answer callback query first to stop the loading spinner
    # We don't answer "check_" or "db_stats" here because they need specific handling (alert or delete)
    if not data.startswith("check_") and data != "db_stats":
        await query.answer()

    if data == "add_new":
        context.user_data['waiting_for_file'] = True
        await query.edit_message_text("📥 أرسل الآن أي (ملف، صورة، فيديو، أو رابط نصي) لإضافته:")
    
    elif data == "db_stats":
        conn = get_db_conn()
        if conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM files")
                count = cur.fetchone()[0]
            conn.close()
            await query.answer(f"📊 إجمالي الروابط في القاعدة: {count}", show_alert=True)

    elif data == "list_content":
        if user_id not in ADMIN_IDS: return
        conn = get_db_conn()
        if not conn: return
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'files'")
                cols = [c['column_name'] for c in cur.fetchall()]
                col_name = 'key' if 'key' in cols else 'file_key'
                cur.execute(f"SELECT {col_name} as final_key, file_type, caption FROM files ORDER BY created_at DESC LIMIT 50")
                rows = cur.fetchall()
            
            if not rows:
                await query.edit_message_text("📭 لا يوجد محتوى مضاف حالياً.")
            else:
                text = "📋 **قائمة آخر 50 محتوى مضاف:**\n\n"
                for row in rows:
                    key = row['final_key']
                    f_type = row['file_type']
                    cap = (row['caption'][:20] + "...") if row['caption'] and len(row['caption']) > 20 else (row['caption'] or "بدون وصف")
                    text += f"🔹 `{key}` | {f_type} | {cap}\n"
                keyboard = [[InlineKeyboardButton("🔙 عودة", callback_data="back_to_admin")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        finally:
            conn.close()

    elif data == "back_to_admin":
        keyboard = [
            [InlineKeyboardButton("➕ إضافة محتوى جديد", callback_data="add_new")],
            [InlineKeyboardButton("📋 قائمة المحتويات", callback_data="list_content")],
            [InlineKeyboardButton("📊 إحصائيات القاعدة", callback_data="db_stats")]
        ]
        await query.edit_message_text("👋 أهلاً بك يا مدير! هذه لوحة التحكم الخاصة بك:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("check_"):
        file_key = data.replace("check_", "").strip()
        # Enforce subscription check ONLY when they click "Get File"
        if await check_subscription(user_id, context.bot):
            await query.answer("✅ تم التحقق بنجاح!")
            await query.delete_message()
            await process_file_request(update, context, file_key)
        else:
            await query.answer("⚠️ عذراً! يجب عليك الاشتراك في القنوات أولاً لتفعيل زر التحميل.", show_alert=True)

async def handle_admin_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS or not context.user_data.get('waiting_for_file'):
        return
    msg = update.message
    logger.info(f"📤 Admin {update.effective_user.id} is uploading content.")
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
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'files'")
                    cols = [c[0] for c in cur.fetchall()]
                    col_name = 'key' if 'key' in cols else 'file_key'
                    cur.execute(f"INSERT INTO files ({col_name}, file_id, file_type, caption) VALUES (%s, %s, %s, %s)", (file_key, f_id, f_type, cap))
                    conn.commit()
                link = f"https://t.me/{BOT_USERNAME}?start={file_key}"
                await msg.reply_text(f"✅ تم الحفظ بنجاح!\n\n🔗 الرابط الخاص بك هو:\n`{link}`", parse_mode='Markdown')
                context.user_data['waiting_for_file'] = False
            finally:
                conn.close()
    else:
        await msg.reply_text("❌ عذراً، يجب إرسال ملف أو رابط صالح.")

# ─────────────────────────────────────────────
# 🌐 KEEP ALIVE (Self-Ping)
# ─────────────────────────────────────────────
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args): return

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

def keep_alive():
    while True:
        try:
            requests.get(RENDER_URL, timeout=10)
            logger.info(f"📡 Self-ping sent to {RENDER_URL}")
        except Exception as e:
            logger.error(f"⚠️ Keep-alive ping failed: {e}")
        time.sleep(180) # 3 minutes

# ─────────────────────────────────────────────
# 🚀 MAIN
# ─────────────────────────────────────────────
def main():
    init_db()
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    
    app = ApplicationBuilder().token(BOT_TOKEN).read_timeout(30).write_timeout(30).connect_timeout(30).pool_timeout(30).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_admin_upload))
    logger.info("🚀 Bot started with Mandatory Reactions for all.")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
