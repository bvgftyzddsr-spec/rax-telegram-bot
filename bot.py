import logging
import hashlib
import time
import os
import threading
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────────────────────────
# ⚙️  CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN     = "8707897595:AAHO2wpxyFcbb6mLrg0UjjpT1yP1T8G4qHY"
CHANNEL_ID    = "@RaX_ViP"
BOT_USERNAME  = "Raxdovipbot"
ADMIN_IDS     = [5614356064]
# رابط قاعدة بيانات Supabase مع كلمة المرور
DATABASE_URL  = "postgresql://postgres:gta738945961@db.jsbxltfpogoiaqiwsevs.supabase.co:5432/postgres"
PORT          = int(os.environ.get("PORT", 8080))
APP_URL       = "https://rax-telegram-bot.onrender.com" 
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Simple Web Server for Render Health Check ───
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running with Supabase!")

def run_health_server():
    try:
        server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
        logger.info(f"🌍 Health server active on port {PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")

# ─── Keep-Alive Logic (Self-Ping) ───
def keep_alive():
    while True:
        try:
            time.sleep(600) # 10 minutes
            requests.get(APP_URL)
            logger.info("📡 Self-ping sent to keep the bot awake.")
        except Exception as e:
            logger.error(f"Keep-alive error: {e}")

# ─── Database Logic (PostgreSQL / Supabase) ───
def get_db_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def db_init():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS files (
                key        TEXT PRIMARY KEY,
                file_id    TEXT NOT NULL,
                file_type  TEXT NOT NULL,
                caption    TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    conn.commit()
    conn.close()

def db_get(key: str):
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT file_id, file_type, caption FROM files WHERE key=%s", (key,))
        row = cur.fetchone()
    conn.close()
    return row

def db_save(key: str, file_id: str, file_type: str, caption: str = ""):
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO files (key, file_id, file_type, caption) VALUES (%s,%s,%s,%s) ON CONFLICT (key) DO UPDATE SET file_id=EXCLUDED.file_id, file_type=EXCLUDED.file_type, caption=EXCLUDED.caption", (key, file_id, file_type, caption))
    conn.commit()
    conn.close()

def db_delete(key: str):
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM files WHERE key=%s", (key,))
    conn.commit()
    conn.close()

def db_list():
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT key, file_type, caption, created_at FROM files ORDER BY created_at DESC")
        rows = cur.fetchall()
    conn.close()
    return rows

# ─── Bot Logic ───
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def type_emoji(file_type: str) -> str:
    return {"document": "📄", "photo": "🖼️", "video": "🎬", "audio": "🎵"}.get(file_type, "📎")

def make_link(key: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={key}"

async def check_subscription(user_id: int, bot) -> bool:
    if is_admin(user_id): return True
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

async def send_content(chat_id: int, row, context: ContextTypes.DEFAULT_TYPE):
    f_id, f_type, cap = row['file_id'], row['file_type'], row['caption'] or ""
    try:
        if f_type == "document": await context.bot.send_document(chat_id=chat_id, document=f_id, caption=cap)
        elif f_type == "photo": await context.bot.send_photo(chat_id=chat_id, photo=f_id, caption=cap)
        elif f_type == "video": await context.bot.send_video(chat_id=chat_id, video=f_id, caption=cap)
        elif f_type == "audio": await context.bot.send_audio(chat_id=chat_id, audio=f_id, caption=cap)
    except Exception as e:
        logger.error(f"Send error: {e}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if is_admin(user_id) and not args:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة محتوى جديد", callback_data="admin:add")],[InlineKeyboardButton("📋 قائمة المحتويات", callback_data="admin:list")],[InlineKeyboardButton("🗑️ حذف محتوى", callback_data="admin:delete_menu")]])
        await update.message.reply_text("🎛️ *لوحة التحكم (Supabase)*", parse_mode="Markdown", reply_markup=kb)
        return
    if not args:
        await update.message.reply_text("👋 أهلاً بك في بوت Rax!\nاستخدم رابطاً خاصاً للحصول على الملفات.")
        return
    key = args[0]
    row = db_get(key)
    if not row:
        await update.message.reply_text("❌ عذراً، هذا الرابط غير صالح أو تم حذفه.")
        return
    
    if await check_subscription(user_id, context.bot):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await send_content(update.effective_chat.id, row, context)
    else:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}")],[InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data=f"verify:{key}")]])
        await update.message.reply_text("🔒 *للحصول على المحتوى يجب الاشتراك في قناتنا أولاً!*\n\n1️⃣ اضغط على الزر للاشتراك\n2️⃣ بعد الاشتراك، اضغط على زر التحقق ✅", parse_mode="Markdown", reply_markup=kb)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    if data.startswith("verify:"):
        key = data.split(":", 1)[1]
        if await check_subscription(user_id, context.bot):
            await query.answer("✅ تم التحقق بنجاح!")
            await query.message.delete()
            row = db_get(key)
            if row: 
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
                await send_content(update.effective_chat.id, row, context)
        else:
            await query.answer("⚠️ عذراً، لم نجد اشتراكك في القناة بعد. يرجى الاشتراك أولاً!", show_alert=True)
        return
    if not is_admin(user_id): return
    await query.answer()
    if data == "admin:main":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة محتوى جديد", callback_data="admin:add")],[InlineKeyboardButton("📋 قائمة المحتويات", callback_data="admin:list")],[InlineKeyboardButton("🗑️ حذف محتوى", callback_data="admin:delete_menu")]])
        await query.edit_message_text("🎛️ *لوحة التحكم*", reply_markup=kb)
    elif data == "admin:add":
        context.user_data["awaiting_file"] = True
        await query.edit_message_text("📤 أرسل الآن أي ملف لإضافته:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")]]))
    elif data == "admin:list":
        rows = db_list()
        if not rows:
            await query.edit_message_text("📋 لا توجد ملفات مضافة.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")]]))
            return
        res = ["📋 *قائمة الملفات المضافة:*\n"]
        for r in rows: res.append(f"{type_emoji(r['file_type'])} `{r['key']}`\n🔗 {make_link(r['key'])}\n")
        await query.edit_message_text("\n".join(res), parse_mode="Markdown", disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")]]))
    elif data == "admin:delete_menu":
        rows = db_list()
        if not rows:
            await query.edit_message_text("🗑️ لا توجد ملفات.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")]]))
            return
        btns = [[InlineKeyboardButton(f"{type_emoji(r['file_type'])} {r['key']}", callback_data=f"admin:del:{r['key']}")] for r in rows]
        btns.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")])
        await query.edit_message_text("🗑️ اختر الملف للحذف:", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("admin:del:"):
        db_delete(data.split("admin:del:", 1)[1])
        await query.answer("✅ تم حذف الملف")
        await callback_handler(update, context)

async def receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id) or not context.user_data.get("awaiting_file"): return
    context.user_data["awaiting_file"] = False
    msg = update.message
    if msg.document: f_id, f_type = msg.document.file_id, "document"
    elif msg.photo: f_id, f_type = msg.photo[-1].file_id, "photo"
    elif msg.video: f_id, f_type = msg.video.file_id, "video"
    elif msg.audio: f_id, f_type = msg.audio.file_id, "audio"
    else: return
    key = hashlib.md5(f"{f_id}{time.time()}".encode()).hexdigest()[:8]
    db_save(key, f_id, f_type, msg.caption or "")
    await msg.reply_text(f"✅ تم حفظ الملف بنجاح!\n\n🔗 رابط المشاركة:\n`{make_link(key)}`", parse_mode="Markdown")

async def post_init(app: Application):
    db_init()
    logger.info("🚀 Bot is ready and connected to Supabase.")

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .post_init(post_init)
        .concurrent_updates(True)
        .build()
    )
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler((filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO) & filters.ChatType.PRIVATE, receive_media))
    
    logger.info("🤖 Starting bot polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
