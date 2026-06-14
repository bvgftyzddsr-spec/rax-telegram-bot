import logging
import hashlib
import time
import asyncio
import aiosqlite
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
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
BOT_TOKEN     = "8707897595:AAEBn6bouINACa7IzhB3Ih1-gn8lESkvk3o"
CHANNELS      = ["@RaX_ViP", "@RaX_ViP2"]
BOT_USERNAME  = "Raxdovipbot"
ADMIN_IDS     = [5614356064]
CHANNEL_FOR_STORAGE_ID = -1003900251919
DB_PATH       = "bot_files.db"
PORT          = int(os.environ.get("PORT", 8080))
# ─────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Simple Web Server for Render ───
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    server = HTTPServer(('0.0.0.0', PORT), HealthCheckHandler)
    logger.info(f"🌍 Health server started on port {PORT}")
    server.serve_forever()

db_connection = None

async def get_db():
    global db_connection
    if db_connection is None:
        db_connection = await aiosqlite.connect(DB_PATH)
        db_connection.row_factory = aiosqlite.Row
    return db_connection

async def db_init():
    db = await get_db()
    await db.execute("""
        CREATE TABLE IF NOT EXISTS files (
            key        TEXT PRIMARY KEY,
            file_id    TEXT NOT NULL,
            file_type  TEXT NOT NULL,
            caption    TEXT,
            url        TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    async with db.execute("PRAGMA table_info(files)") as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
        if 'url' not in columns:
            await db.execute("ALTER TABLE files ADD COLUMN url TEXT")
    await db.commit()

async def db_get(key: str):
    db = await get_db()
    async with db.execute("SELECT file_id, file_type, caption, url FROM files WHERE key=?", (key,)) as cur:
        return await cur.fetchone()

async def db_save(key: str, file_id: str, file_type: str, caption: str = "", url: str = "", context: ContextTypes.DEFAULT_TYPE = None):
    db = await get_db()
    await db.execute("INSERT OR REPLACE INTO files (key, file_id, file_type, caption, url) VALUES (?,?,?,?,?)", (key, file_id, file_type, caption, url))
    await db.commit()
    
    if context:
        try:
            backup_text = f"📦 نسخة احتياطية\n\n🔑 الكود: {key}\n📁 النوع: {file_type}\n📝 الوصف: {caption or 'لا يوجد'}\n🔗 الرابط: {url or file_id}\n\n#backup_{key}"
            await context.bot.send_message(chat_id=CHANNEL_FOR_STORAGE_ID, text=backup_text)
            logger.info(f"✅ Backup sent for {key}")
        except Exception as e:
            logger.error(f"Backup error: {e}")

async def db_delete(key: str):
    db = await get_db()
    await db.execute("DELETE FROM files WHERE key=?", (key,))
    await db.commit()

async def db_list():
    db = await get_db()
    async with db.execute("SELECT key, file_type, caption, url, created_at FROM files ORDER BY created_at DESC") as cur:
        return await cur.fetchall()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def type_emoji(file_type: str) -> str:
    return {"document": "📄", "photo": "🖼️", "video": "🎬", "audio": "🎵", "link": "🔗"}.get(file_type, "📎")

def make_link(key: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={key}"

async def check_subscription(user_id: int, bot) -> bool:
    if is_admin(user_id): return True
    for channel in CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            return False
    return True

async def send_content(chat_id: int, row, context: ContextTypes.DEFAULT_TYPE):
    f_id, f_type, cap, url = row['file_id'], row['file_type'], row['caption'] or "", row['url'] or ""
    try:
        if f_type == "document": await context.bot.send_document(chat_id=chat_id, document=f_id, caption=cap)
        elif f_type == "photo": await context.bot.send_photo(chat_id=chat_id, photo=f_id, caption=cap)
        elif f_type == "video": await context.bot.send_video(chat_id=chat_id, video=f_id, caption=cap)
        elif f_type == "audio": await context.bot.send_audio(chat_id=chat_id, audio=f_id, caption=cap)
        elif f_type == "link": await context.bot.send_message(chat_id=chat_id, text=url, disable_web_page_preview=False)
    except Exception as e:
        logger.error(f"Send error: {e}")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if is_admin(user_id) and not args:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة محتوى جديد", callback_data="admin:add")],[InlineKeyboardButton("📋 قائمة المحتويات", callback_data="admin:list")],[InlineKeyboardButton("🗑️ حذف محتوى", callback_data="admin:delete_menu")]])
        await update.message.reply_text("🎛️ *لوحة التحكم*", parse_mode="Markdown", reply_markup=kb)
        return
    if not args:
        await update.message.reply_text("👋 أهلاً! استخدم رابطاً خاصاً للحصول على المحتوى.")
        return
    key = args[0]
    row = await db_get(key)
    if not row:
        await update.message.reply_text("❌ الرابط غير صالح.")
        return
    
    if await check_subscription(user_id, context.bot):
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        await send_content(update.effective_chat.id, row, context)
    else:
        msg = "🔒 *للحصول على المحتوى يجب الاشتراك في القنوات أولاً:*\n\n"
        btns = []
        for i, channel in enumerate(CHANNELS, 1):
            btns.append([InlineKeyboardButton(f"📢 قناة رقم {i}", url=f"https://t.me/{channel.lstrip('@')}")])
        btns.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data=f"verify:{key}")])
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    if data.startswith("verify:"):
        key = data.split(":", 1)[1]
        if await check_subscription(user_id, context.bot):
            await query.answer("✅ تم التحقق بنجاح!")
            await query.message.delete()
            row = await db_get(key)
            if row: 
                await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
                await send_content(update.effective_chat.id, row, context)
        else:
            await query.answer("⚠️ لم تشترك في جميع القنوات بعد!", show_alert=True)
        return
    if not is_admin(user_id): return
    await query.answer()
    if data == "admin:main":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ إضافة محتوى جديد", callback_data="admin:add")],[InlineKeyboardButton("📋 قائمة المحتويات", callback_data="admin:list")],[InlineKeyboardButton("🗑️ حذف محتوى", callback_data="admin:delete_menu")]])
        await query.edit_message_text("🎛️ *لوحة التحكم*", reply_markup=kb)
    elif data == "admin:add":
        context.user_data["awaiting_file"] = True
        await query.edit_message_text("📤 أرسل الملف أو الرابط الآن:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")]]))
    elif data == "admin:list":
        rows = await db_list()
        if not rows:
            await query.edit_message_text("📋 فارغ.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")]]))
            return
        res = ["📋 *المحتويات:*\n"]
        for r in rows:
            if r["file_type"] == "link":
                res.append(f"{type_emoji(r['file_type'])} `{r['key']}`\n🔗 {r['url']}\n")
            else:
                res.append(f"{type_emoji(r['file_type'])} `{r['key']}`\n🔗 {make_link(r['key'])}\n")
        await query.edit_message_text("\n".join(res), parse_mode="Markdown", disable_web_page_preview=True, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")]]))
    elif data == "admin:delete_menu":
        rows = await db_list()
        if not rows:
            await query.edit_message_text("🗑️ لا يوجد شيء.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")]]))
            return
        btns = [[InlineKeyboardButton(f"{type_emoji(r['file_type'])} {r['key']}", callback_data=f"admin:del:{r['key']}")] for r in rows]
        btns.append([InlineKeyboardButton("🔙 رجوع", callback_data="admin:main")])
        await query.edit_message_text("🗑️ اختر للحذف:", reply_markup=InlineKeyboardMarkup(btns))
    elif data.startswith("admin:del:"):
        await db_delete(data.split("admin:del:", 1)[1])
        await query.answer("✅ تم الحذف")
        await callback_handler(update, context)

async def receive_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id) or not context.user_data.get("awaiting_file"): return
    context.user_data["awaiting_file"] = False
    msg = update.message
    
    if msg.text and (msg.text.startswith("http://") or msg.text.startswith("https://")):
        f_id, f_type = msg.text, "link"
        key = hashlib.md5(f"{f_id}{time.time()}".encode()).hexdigest()[:8]
        await db_save(key, f_id, f_type, msg.caption or "", url=f_id, context=context)
    else:
        if msg.document: f_id, f_type = msg.document.file_id, "document"
        elif msg.photo: f_id, f_type = msg.photo[-1].file_id, "photo"
        elif msg.video: f_id, f_type = msg.video.file_id, "video"
        elif msg.audio: f_id, f_type = msg.audio.file_id, "audio"
        else: return
        key = hashlib.md5(f"{f_id}{time.time()}".encode()).hexdigest()[:8]
        await db_save(key, f_id, f_type, msg.caption or "", context=context)
        
    await msg.reply_text(f"✅ تم الحفظ!\n\n🔗 الرابط:\n`{make_link(key)}`")

async def post_init(app: Application):
    await db_init()
    logger.info("🚀 البوت جاهز للعمل بالحالة المستقرة")

def main():
    threading.Thread(target=run_health_server, daemon=True).start()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .concurrent_updates(True)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler((filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.TEXT) & filters.ChatType.PRIVATE, receive_media))
    
    logger.info("🤖 بدء تشغيل البوت...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
