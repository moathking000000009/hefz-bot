# -*- coding: utf-8 -*-
"""
Upgraded Telegram Bot for جمعية حفظ النعمة
Features:
- Rate limiting
- Automatic backups
- Better error handling
- Statistics tracking
- Health monitoring
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)

from config import Config
from utils import (
    setup_logging, rate_limiter, data_manager, groq_client,
    detect_intent, mask_sensitive_data
)

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

class TelegramBot:
    """Main bot class with enhanced functionality"""
    
    def __init__(self):
        self.app = None
        self.is_running = False
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        user = update.effective_user
        logger.info("🚀 /start from @%s (%s)", user.username, user.id)
        
        welcome_message = """
مرحبًا! أنا مساعد جمعية حفظ النعمة بحائل. 🌟

يمكنني مساعدتك في:
• التبرع بفائض الطعام 🍽️
• طلب مساعدة غذائية 📦
• التسجيل كمتطوع 🤝
• الاستفسارات العامة ❓

أرسل لي رسالتك وسأقوم بمساعدتك!
        """.strip()
        
        await update.message.reply_text(welcome_message)
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command (admin only)"""
        user = update.effective_user
        
        # Simple admin check (you can enhance this)
        if user.id not in [123456789]:  # Replace with actual admin IDs
            await update.message.reply_text("⚠️ هذا الأمر متاح للمشرفين فقط.")
            return
        
        stats = data_manager.get_statistics()
        
        stats_message = f"""
📊 إحصائيات البوت:

إجمالي الطلبات: {stats['total_requests']}
طلبات اليوم: {stats['today_requests']}

توزيع الطلبات:
"""
        
        for intent, count in stats.get('intents', {}).items():
            stats_message += f"• {intent}: {count}\n"
        
        await update.message.reply_text(stats_message)
    
    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /backup command (admin only)"""
        user = update.effective_user
        
        # Simple admin check
        if user.id not in [123456789]:  # Replace with actual admin IDs
            await update.message.reply_text("⚠️ هذا الأمر متاح للمشرفين فقط.")
            return
        
        await update.message.reply_text("🔄 جاري إنشاء نسخة احتياطية...")
        
        backup_path = data_manager.create_backup()
        if backup_path:
            await update.message.reply_text(f"✅ تم إنشاء النسخة الاحتياطية: {backup_path}")
        else:
            await update.message.reply_text("❌ فشل في إنشاء النسخة الاحتياطية")
    
    async def health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /health command"""
        user = update.effective_user
        logger.info("🏥 Health check from @%s (%s)", user.username, user.id)
        
        health_status = "✅ البوت يعمل بشكل طبيعي"
        
        # Check if Excel file is accessible
        try:
            data_manager.get_statistics()
        except Exception as e:
            health_status = f"⚠️ مشكلة في قاعدة البيانات: {str(e)}"
        
        await update.message.reply_text(health_status)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages with rate limiting"""
        try:
            user = update.effective_user
            user_text = (update.message.text or "").strip()
            
            # Rate limiting check
            if not rate_limiter.is_allowed(user.id):
                await update.message.reply_text(
                    "⚠️ عذرًا، لقد تجاوزت الحد المسموح من الرسائل. يرجى الانتظار قليلاً."
                )
                return
            
            # Skip empty messages
            if not user_text:
                return
            
            logger.info("📩 Message from @%s (%s): %s", user.username, user.id, user_text[:50])
            
            # Detect intent
            intent = detect_intent(user_text)
            
            # Get AI response
            reply = groq_client.ask(user_text)
            
            # Prepare data for storage
            row_data = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "intent": intent,
                "message": user_text,
                "reply": reply,
            }
            
            # Save to Excel
            data_manager.save_to_excel(row_data)
            
            # Send response
            await update.message.reply_text(reply if reply else "⚠️ لم أتمكن من معالجة رسالتك.")
            
        except Exception as e:
            logger.error("❌ handle_message error: %s", e, exc_info=True)
            await update.message.reply_text("⚠️ حدث خطأ أثناء معالجة رسالتك.")
    
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors"""
        logger.exception("💥 Unhandled error", exc_info=context.error)
    
    def close_webhook_sync(self, token: str, drop_pending: bool = True) -> None:
        """Close webhook synchronously"""
        try:
            url = f"https://api.telegram.org/bot{token}/deleteWebhook"
            data = {"drop_pending_updates": "true" if drop_pending else "false"}
            response = requests.post(url, data=data, timeout=Config.REQUEST_TIMEOUT)
            
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            
            logger.info("🧹 deleteWebhook -> %s %s", response.status_code, payload)
        except Exception as e:
            logger.warning("⚠️ Could not delete webhook: %s", e)
    
    def setup_handlers(self) -> None:
        """Setup bot handlers"""
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("backup", self.backup_command))
        self.app.add_handler(CommandHandler("health", self.health_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.app.add_error_handler(self.error_handler)
    
    def run(self) -> None:
        """Run the bot"""
        try:
            # Validate configuration
            Config.validate()
            Config.create_directories()
            
            # Log startup info
            logger.info("🚀 Starting bot with config -> BOT=%s, GROQ=%s", 
                       mask_sensitive_data(Config.BOT_TOKEN), 
                       mask_sensitive_data(Config.GROQ_API_KEY))
            
            # Close any existing webhook
            self.close_webhook_sync(Config.BOT_TOKEN, drop_pending=True)
            
            # Create and configure application
            self.app = ApplicationBuilder().token(Config.BOT_TOKEN).build()
            self.setup_handlers()
            
            # Start polling
            logger.info("✅ Bot is starting with enhanced features...")
            self.is_running = True
            self.app.run_polling(drop_pending_updates=True)
            
        except KeyboardInterrupt:
            logger.info("🔴 Bot stopped manually.")
        except Exception as e:
            logger.error("❌ Bot startup failed: %s", e)
            raise
        finally:
            self.is_running = False

def main():
    """Main entry point"""
    bot = TelegramBot()
    bot.run()

if __name__ == "__main__":
    main()
