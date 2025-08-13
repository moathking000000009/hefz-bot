from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8046571027:AAGnlyDvfSqTJJ8izn9EEhlNWcnfnDe7TCU" 

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"🚀 تم استقبال أمر /start من {update.message.from_user.username}")
    await update.message.reply_text("مرحبًا! البوت يعمل ✅")

# أي رسالة نصية
async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.username
    text = update.message.text
    print(f"📩 رسالة من {user}: {text}")
    await update.message.reply_text(f"سمعتك تقول: {text}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    print("✅ البوت البسيط يعمل...")
    app.run_polling()
