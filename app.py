import os
import sqlite3
import uuid
import threading
import time
from datetime import datetime, timedelta
from telegram import Bot, Update, InputFile
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import logging

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Config
BOT_TOKEN = "8450810474:AAFNS7t91adMDxUdhV6QvnFeqfs1A-JG1VM"
ADMIN_ID = 7595763645  # Your admin ID
bot = Bot(BOT_TOKEN)

# Database setup
def init_db():
    conn = sqlite3.connect('files.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS files
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  file_id TEXT UNIQUE,
                  telegram_file_id TEXT,
                  file_name TEXT,
                  file_size INTEGER,
                  upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  admin_id INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# Auto-delete files after 1 minute
def auto_delete_worker():
    while True:
        try:
            conn = sqlite3.connect('files.db')
            c = conn.cursor()
            
            # Find files older than 1 minute
            c.execute("SELECT file_id, telegram_file_id, file_name FROM files WHERE datetime(upload_time) < datetime('now', '-1 minute')")
            old_files = c.fetchall()
            
            for file_data in old_files:
                file_id, telegram_file_id, file_name = file_data
                
                # Delete from database
                c.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
                conn.commit()
                
                # Delete temporary file if exists
                temp_file = f"temp_{file_id}_{file_name}"
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                
                print(f"Deleted file: {file_name}")
            
            conn.close()
        except Exception as e:
            print(f"Error in auto_delete_worker: {e}")
        
        time.sleep(30)  # Check every 30 seconds

# Start auto-delete thread
delete_thread = threading.Thread(target=auto_delete_worker)
delete_thread.daemon = True
delete_thread.start()

# Telegram Bot
def telegram_bot():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    def is_admin(user_id):
        return user_id == ADMIN_ID
    
    # Admin panel command
    def admin_panel(update: Update, context: CallbackContext):
        if not is_admin(update.effective_user.id):
            update.message.reply_text("❌ Bu komutu kullanma yetkiniz yok.")
            return
        
        keyboard = [
            [InlineKeyboardButton("📤 Dosya Yükle", callback_data='upload_file')],
            [InlineKeyboardButton("📊 Yüklenen Dosyalar", callback_data='list_files')],
            [InlineKeyboardButton("🔄 Botu Başlat", callback_data='start_bot')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        update.message.reply_text(
            "🏠 **Admin Paneli**\n\n"
            "Aşağıdaki seçeneklerden birini seçin:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    # Handle button callbacks
    def button_handler(update: Update, context: CallbackContext):
        query = update.callback_query
        query.answer()
        
        if not is_admin(query.from_user.id):
            query.edit_message_text("❌ Bu işlemi yapma yetkiniz yok.")
            return
        
        if query.data == 'upload_file':
            query.edit_message_text(
                "📤 **Dosya Yükleme**\n\n"
                "Lütfen yüklemek istediğiniz dosyayı gönderin. "
                "Dosya otomatik olarak işlenecek ve paylaşım linki oluşturulacaktır.",
                parse_mode='Markdown'
            )
        
        elif query.data == 'list_files':
            conn = sqlite3.connect('files.db')
            c = conn.cursor()
            c.execute("SELECT file_id, file_name, upload_time FROM files WHERE admin_id = ? ORDER BY upload_time DESC LIMIT 10", (ADMIN_ID,))
            files = c.fetchall()
            conn.close()
            
            if not files:
                query.edit_message_text("📭 Henüz hiç dosya yüklenmemiş.")
                return
            
            files_text = "📁 **Son Yüklenen Dosyalar:**\n\n"
            for file in files:
                file_id, file_name, upload_time = file
                time_left = "1 dakikadan az"  # Simplified time display
                bot_link = f"https://t.me/{(bot.get_me()).username}?start={file_id}"
                files_text += f"📄 {file_name}\n🔗 `{bot_link}`\n⏰ {time_left}\n\n"
            
            query.edit_message_text(files_text, parse_mode='Markdown')
        
        elif query.data == 'start_bot':
            query.edit_message_text(
                "🤖 **Bot Aktif**\n\n"
                "Bot şu anda çalışıyor. Kullanıcılar oluşturduğunuz linkler üzerinden dosyalara erişebilir.",
                parse_mode='Markdown'
            )
    
    # Handle file uploads from admin
    def handle_file(update: Update, context: CallbackContext):
        if not is_admin(update.effective_user.id):
            return
        
        if update.message.document:
            file = update.message.document
        elif update.message.photo:
            file = update.message.photo[-1]
        elif update.message.video:
            file = update.message.video
        elif update.message.audio:
            file = update.message.audio
        else:
            update.message.reply_text("❌ Desteklenmeyen dosya türü.")
            return
        
        # Generate unique file ID
        file_id = str(uuid.uuid4())[:8]
        file_name = file.file_name if hasattr(file, 'file_name') else f"file_{file_id}"
        
        # Get file from Telegram
        file_obj = bot.get_file(file.file_id)
        
        # Download file temporarily
        temp_path = f"temp_{file_id}_{file_name}"
        file_obj.download(temp_path)
        
        # Save to database
        conn = sqlite3.connect('files.db')
        c = conn.cursor()
        c.execute("INSERT INTO files (file_id, telegram_file_id, file_name, file_size, admin_id) VALUES (?, ?, ?, ?, ?)",
                 (file_id, file.file_id, file_name, file.file_size, ADMIN_ID))
        conn.commit()
        conn.close()
        
        # Generate bot link
        bot_username = (bot.get_me()).username
        bot_link = f"https://t.me/{bot_username}?start={file_id}"
        
        # Send success message with link
        update.message.reply_text(
            f"✅ **Dosya Başarıyla Yüklendi!**\n\n"
            f"📄 Dosya: `{file_name}`\n"
            f"🔗 Paylaşım Linki:\n`{bot_link}`\n\n"
            f"⏰ Bu dosya 1 dakika sonra otomatik olarak silinecektir.",
            parse_mode='Markdown'
        )
    
    # Handle start command for users
    def start(update: Update, context: CallbackContext):
        if context.args:
            file_id = context.args[0]
            
            conn = sqlite3.connect('files.db')
            c = conn.cursor()
            c.execute("SELECT * FROM files WHERE file_id = ?", (file_id,))
            file_data = c.fetchone()
            
            if file_data:
                # Send file directly using Telegram file_id
                try:
                    if update.message.document is None:  # Only send if not already a file
                        context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=file_data[2],  # telegram_file_id
                            caption=f"📄 {file_data[3]}\n\n⏰ Bu dosya 1 dakika sonra silinecektir."
                        )
                except Exception as e:
                    update.message.reply_text("❌ Dosya gönderilirken hata oluştu.")
            else:
                update.message.reply_text("❌ Geçersiz veya süresi dolmuş link!")
            
            conn.close()
        else:
            if is_admin(update.effective_user.id):
                admin_panel(update, context)
            else:
                update.message.reply_text(
                    "🤖 **Dosya Dağıtım Botu**\n\n"
                    "Bu bot sadece özel dosya linkleri ile çalışır. "
                    "Geçerli bir dosya linkiniz yoksa admin ile iletişime geçin.",
                    parse_mode='Markdown'
                )
    
    # Handle other messages
    def handle_message(update: Update, context: CallbackContext):
        if is_admin(update.effective_user.id):
            update.message.reply_text(
                "Admin komutları için /admin yazın veya bir dosya gönderin.",
                parse_mode='Markdown'
            )
        else:
            update.message.reply_text(
                "Bu bot sadece özel dosya linkleri ile çalışır.",
                parse_mode='Markdown'
            )
    
    # Add handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("admin", admin_panel))
    dp.add_handler(MessageHandler(Filters.document | Filters.photo | Filters.video | Filters.audio, handle_file))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(MessageHandler(Filters.text, handle_message))
    
    # Callback query handler
    from telegram.ext import CallbackQueryHandler
    dp.add_handler(CallbackQueryHandler(button_handler))
    
    # Start the bot
    print("Bot started...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    telegram_bot()
