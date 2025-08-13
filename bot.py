# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import logging
import os
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from groq import Groq
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ---------- ENV ----------
load_dotenv()  # harmless on Railway; it uses Variables tab
BOT_TOKEN = os.getenv("BOT")           # set in Railway Variables
GROQ_API_KEY = os.getenv("GROQ")       # set in Railway Variables
EXCEL_FILE = "requests.xlsx"

def _mask(v: str, show=6):
    if not v: return "None"
    return v[:show] + "…" + v[-4:]

# fail fast with clear logs (without leaking full secrets)
if not BOT_TOKEN or not GROQ_API_KEY:
    logging.error("Missing env vars. BOT=%s, GROQ=%s",
                  _mask(BOT_TOKEN), _mask(GROQ_API_KEY))
    raise ValueError("Missing BOT or GROQ environment variables.")

# ---------- Prompt ----------
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

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ---------- Groq ----------
client = Groq(api_key=GROQ_API_KEY)

def ask_groq(user_message: str) -> str:
    try:
        res = client.chat.completions.create(
            model="llama3-8b-8192",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
        )
        reply = res.choices[0].message.content
        logging.info("Groq reply OK")
        return reply
    except Exception as e:
        logging.error("Groq Error: %s", e)
        return "⚠️ عذرًا، حدث خطأ أثناء الاتصال بالنموذج."

# ---------- Storage ----------
def save_to_excel(row: dict):
    try:
        if os.path.exists(EXCEL_FILE):
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl")
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
    except Exception as e:
        logging.error("Excel save error: %s", e)

# ---------- Intent ----------
def detect_intent(text: str) -> str:
    t = text or ""
    if "تبرع" in t:
        return "DONATION_FOOD"
    if "سلة" in t or "مساعدة" in t:
        return "BENEFICIARY_REQUEST"
    if "تطوع" in t:
        return "VOLUNTEER_SIGNUP"
    return "OTHER"

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.info("Received /start from %s", update.effective_user.username)
    await update.message.reply_text("مرحبًا! أنا مساعد جمعية حفظ النعمة بحائل. كيف أقدر أخدمك؟")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_text = (update.message.text or "").strip()
        user = update.effective_user
        intent = detect_intent(user_text)
        reply = ask_groq(user_text)

        save_to_excel({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user.id,
            "username": user.username,
            "intent": intent,
            "message": user_text,
            "reply": reply,
        })

        await update.message.reply_text(reply if reply else "⚠️ لم أتمكن من معالجة رسالتك.")
    except Exception as e:
        logging.error("handle_message error: %s", e)
        await update.message.reply_text("⚠️ حدث خطأ أثناء معالجة رسالتك.")

# ---------- Run ----------
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info("Bot starting… BOT=%s, GROQ=%s", _mask(BOT_TOKEN), _mask(GROQ_API_KEY))
    app.run_polling()
