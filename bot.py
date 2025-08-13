# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import logging
import pandas as pd
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq
from dotenv import load_dotenv
import os
from datetime import datetime

# ====== تحميل القيم من ملف .env ======
load_dotenv()
BOT_TOKEN = os.getenv("BOT")
GROQ_API_KEY = os.getenv("GROQ")
EXCEL_FILE = "requests.xlsx"

# ====== System Prompt ======
SYSTEM_PROMPT = """
أنت مساعد افتراضي رسمي لجمعية حفظ النعمة بمنطقة حائل. دورك خدمة:
1) المتبرعين بفائض الطعام/الأثاث/الملابس،
2) المستفيدين (الأسر المحتاجة)،
3) المتطوعين،
4) الاستفسارات العامة والشكاوى.

منطقة الخدمة: مدينة حائل والمراكز التابعة لها.
أوقات العمل: من الأحد إلى الخميس، 8:00 صباحًا – 9:00 مساءً.
رقم التواصل: 0551965445.
سياسات السلامة: رفض الطعام غير المعبأ أو غير الآمن، حفظ سرية البيانات.

صنّف الرسائل إلى: DONATION_FOOD / BENEFICIARY_REQUEST / VOLUNTEER_SIGNUP / OTHER.
أجب بطريقة ودودة، مختصرة، ومنظمة.
"""

# ====== إعداد السجل ======
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

# ====== تهيئة Groq ======
client = Groq(api_key=GROQ_API_KEY)

# ====== دالة تصنيف الرسائل ======
def detect_intent(text):
    if "تبرع" in text:
        return "DONATION_FOOD"
    elif "سلة" in text or "مساعدة" in text:
        return "BENEFICIARY_REQUEST"
    elif "تطوع" in text:
        return "VOLUNTEER_SIGNUP"
    else:
        return "OTHER"

# ====== دالة Groq ======
def ask_groq(user_message):
    try:
        response = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}
            ],
            temperature=0.4
        )
        reply_text = response.choices[0].message.content
        logging.info(f"✅ رد Groq: {reply_text}")
        return reply_text
    except Exception as e:
        logging.error(f"❌ Groq Error: {e}")
        return "⚠️ عذرًا، حدث خطأ أثناء الاتصال بالنموذج."

# ====== حفظ البيانات ======
def save_to_excel(data):
    try:
        if os.path.exists(EXCEL_FILE):
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl")
            df = pd.concat([df, pd.DataFrame([data])], ignore_index=True)
        else:
            df = pd.DataFrame([data])
        df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
    except Exception as e:
        logging.error(f"❌ خطأ في حفظ البيانات: {e}")

# ====== أوامر البوت ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("🚀 استقبل أمر /start")
    await update.message.reply_text("مرحبًا! أنا مساعد جمعية حفظ النعمة بحائل. كيف أقدر أخدمك؟")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_text = update.message.text.strip()
        user_id = update.message.from_user.id
        username = update.message.from_user.username

        logging.info(f"📩 رسالة من {username} (ID: {user_id}): {user_text}")

        # تحديد النية
        intent = detect_intent(user_text)

        # الحصول على رد من Groq
        groq_reply = ask_groq(user_text)

        # حفظ الطلب
        save_to_excel({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user_id,
            "username": username,
            "intent": intent,
            "message": user_text,
            "reply": groq_reply
        })

        # الرد على المستخدم
        await update.message.reply_text(groq_reply if groq_reply else "⚠️ لم أتمكن من معالجة رسالتك.")
    except Exception as e:
        logging.error(f"❌ خطأ في handle_message: {e}")
        await update.message.reply_text("⚠️ حدث خطأ أثناء معالجة رسالتك.")

# ====== تشغيل البوت ======
if __name__ == "__main__":
    if not BOT_TOKEN or not GROQ_API_KEY:
        logging.error("❌ تأكد من وضع BOT_TOKEN و GROQ_API_KEY في ملف .env")
        sys.exit(1)

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("✅ البوت يعمل باستخدام Groq API...")
    app.run_polling()

