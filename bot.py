"""
Telegram Bot: Helpers and entrypoint

This script defines a Telegram bot for the Hefz Association in Hail.  The bot
responds to text messages in Arabic, classifies the intent (food donation,
beneficiary request, volunteer signup or other), calls Groq's LLM to generate
a brief reply and persists each interaction to an Excel file.  The
implementation focuses on simplicity, reliability and clarity:

* **Single instance**: The bot locks a local TCP port to ensure only one
  instance runs at a time on the host.  If another instance is detected the
  process exits with a clear error.
* **Webhook cleanup**: On startup the script synchronously deletes any
  previously configured webhook, dropping pending updates to avoid conflicts
  between webhook and polling modes.
* **Environment handling**: A small helper normalises environment variables,
  stripping stray quotes and accidental `NAME=value` prefixes.  Required
  variables are validated up-front.
* **Intent classification**: A minimal keyword-based classifier recognises
  food donation, beneficiary requests and volunteer registrations.  Keywords
  for furniture or clothing have been removed per the user's request.
* **Asynchronous handlers**: Handlers in python‑telegram‑bot v20+ are
  asynchronous; this script uses them but avoids explicit event loop
  management by relying on `run_polling()` for polling and `requests`
  synchronously for webhook cleanup.
* **Persistent logging**: Errors in the handlers or network operations are
  logged with stack traces for easier debugging.  The bot exits gracefully
  when encountering a Telegram `Conflict` error (another process using the
  same token).

The script is designed to run with minimal external dependencies: only
`telegram`, `groq`, `dotenv`, `pandas` and `requests` are required.  To run
the bot locally, create a `.env` file with the variables `BOT_TOKEN` and
`GROQ_API_KEY` (or their aliases `BOT` and `GROQ`) and execute `python
bot.py`.  When deploying to a server, ensure no other process is polling the
same token to avoid 409 conflicts.
"""

import logging
import os
import socket
import sys
from datetime import datetime
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv
from groq import Groq
from telegram import Update
from telegram.error import Conflict
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# ---------------------------------------------------------------------------
# Environment configuration

# Load environment variables from .env if present.  This call is idempotent.
load_dotenv()


def _clean_env(name: str) -> Optional[str]:
    """Read and normalise an environment variable.

    This helper strips common mistakes when defining variables, such as
    accidental quotes or `NAME=value` prefixes.  Returns ``None`` if the
    variable is not set or empty after cleaning.

    Args:
        name: The name of the environment variable to retrieve.

    Returns:
        A cleaned string or ``None``.
    """
    value = os.getenv(name)
    if value is None:
        return None
    # Remove surrounding quotes and whitespace
    value = value.strip().strip("\"").strip("'")
    # If the value is accidentally given as NAME=value, strip the prefix
    prefix = f"{name}="
    if value.startswith(prefix):
        value = value[len(prefix) :].strip()
    # Also handle accidental '=value' forms
    if value.startswith("="):
        value = value[1:].strip()
    return value or None


def _mask(value: Optional[str], head: int = 6, tail: int = 4) -> str:
    """Mask sensitive values for logging.

    Shows only the first ``head`` characters and last ``tail`` characters of
    the value, with an ellipsis in between.  If the value is ``None`` or
    shorter than the combined head and tail, the original string is returned.

    Args:
        value: The value to mask.
        head: Number of characters to show from the start.
        tail: Number of characters to show from the end.

    Returns:
        The masked value as a string.
    """
    if not value:
        return "None"
    if len(value) <= head + tail:
        return value
    return f"{value[:head]}…{value[-tail:]}"


# Extract tokens from environment (supporting multiple names for convenience)
BOT_TOKEN: Optional[str] = _clean_env("BOT_TOKEN") or _clean_env("BOT")
GROQ_API_KEY: Optional[str] = _clean_env("GROQ_API_KEY") or _clean_env("GROQ")
EXCEL_FILE: str = "requests.xlsx"


# Configure logging early so that log messages appear during module import
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logger.info(
    "Boot env -> BOT=%s, GROQ=%s",
    _mask(BOT_TOKEN),
    _mask(GROQ_API_KEY),
)

if not BOT_TOKEN or not GROQ_API_KEY:
    raise SystemExit(
        "❌ Missing env: BOT_TOKEN/BOT and GROQ_API_KEY/GROQ must be set."
    )


# ---------------------------------------------------------------------------
# Single instance lock

_singleton_sock: Optional[socket.socket] = None


def ensure_single_instance(port: int = 8765) -> None:
    """Prevent multiple local instances of the bot.

    Attempts to bind to a local TCP port.  If binding fails, it is assumed
    that another instance is already running (and has locked the port).  In
    that case the process exits with a logged error message.

    Args:
        port: The port number to bind for exclusivity.  It must remain
            consistent across invocations; choose a port that is unlikely to
            conflict with other local services.
    """
    global _singleton_sock
    _singleton_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _singleton_sock.bind(("127.0.0.1", port))
    except OSError:
        logger.error(
            "⚠️ Another instance of the bot appears to be running (port %d locked).",
            port,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# System prompt and Groq API

SYSTEM_PROMPT: str = """
أنت مساعد افتراضي رسمي لجمعية حفظ النعمة بمنطقة حائل. دورك خدمة:
1) المتبرعين بفائض الطعام،
2) المستفيدين (الأسر المحتاجة)،
3) المتطوعين،
4) الاستفسارات العامة والشكاوى.
منطقة الخدمة: مدينة حائل والمراكز التابعة لها.
أوقات العمل: من الأحد إلى الخميس، 8:00 صباحًا – 9:00 مساءً.
رقم التواصل/واتساب: 0551965445.
سياسات السلامة:
- قبول الطعام المعبأ أو المطهي حديثًا وفق معايير السلامة ورفض غير الآمن.
- الحفاظ على سرية البيانات.
صنّف الرسائل إلى: DONATION_FOOD / BENEFICIARY_REQUEST / VOLUNTEER_SIGNUP / OTHER.
أجب بالعربية المختصرة واطلب الحقول الناقصة.
"""


client = Groq(api_key=GROQ_API_KEY)


def _ask_groq(user_message: str) -> str:
    """Call Groq's API synchronously to generate a reply.

    The model is called with the system prompt and user message.  A low
    temperature encourages concise, deterministic responses.  Any exceptions
    during the call are logged and a fallback message is returned.

    Args:
        user_message: The user's message text.

    Returns:
        A reply generated by the Groq model or a fallback error message.
    """
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
        logger.debug("Groq raw response: %s", reply)
        logger.info("✅ Groq reply OK")
        return reply
    except Exception as exc:
        logger.error("❌ Groq Error: %s", exc)
        return "⚠️ عذرًا، حدث خطأ أثناء الاتصال بالنموذج."


def _save_to_excel(row: dict) -> None:
    """Append a row to the Excel log.

    Reads the existing file if present, concatenates the new row, and writes
    back.  The function is synchronous; if high throughput is required,
    consider moving this to a separate thread via ``asyncio.to_thread``.

    Args:
        row: A dictionary of column names to values to append.
    """
    try:
        if os.path.exists(EXCEL_FILE):
            df = pd.read_excel(EXCEL_FILE, engine="openpyxl")
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df = pd.DataFrame([row])
        df.to_excel(EXCEL_FILE, index=False, engine="openpyxl")
        logger.info("✅ Data saved to Excel")
    except Exception as exc:
        logger.error("❌ Excel save error: %s", exc)


# ---------------------------------------------------------------------------
# Intent detection (food only)


def detect_intent(text: str) -> str:
    """Classify a user's message into a coarse intent.

    The intent detection here is intentionally simple and keyword-based:

    * If the message contains "تبرع" or any of the food keywords (طعام,
      أكل, وجبات, وليمة) the intent is considered a food donation.
    * If it contains keywords associated with requests for help (سلة, مساعدة,
      معونة, احتاج, محتاجة) then it's classified as a beneficiary request.
    * If it contains volunteer-related words (تطوع, متطوع, تطوّع) it's a
      volunteer signup.
    * Otherwise the intent is unknown/other.

    Args:
        text: The user's message text.

    Returns:
        One of "DONATION_FOOD", "BENEFICIARY_REQUEST",
        "VOLUNTEER_SIGNUP" or "OTHER".
    """
    t = (text or "").strip()
    # Food donation keywords
    if "تبرع" in t or any(k in t for k in ["طعام", "أكل", "وجبات", "وليمة"]):
        return "DONATION_FOOD"
    # Beneficiary request keywords
    if any(k in t for k in ["سلة", "مساعدة", "معونة", "احتاج", "محتاجة"]):
        return "BENEFICIARY_REQUEST"
    # Volunteer signup keywords
    if any(k in t for k in ["تطوع", "متطوع", "تطوّع"]):
        return "VOLUNTEER_SIGNUP"
    return "OTHER"


# ---------------------------------------------------------------------------
# Telegram handlers


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply to /start command with a welcome message."""
    user = update.effective_user
    logger.info("🚀 /start from @%s (%s)", user.username, user.id)
    await update.message.reply_text(
        "مرحبًا! أنا مساعد جمعية حفظ النعمة بحائل. كيف أقدر أخدمك؟"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Process a normal text message from the user."""
    try:
        user_text = (update.message.text or "").strip()
        user = update.effective_user

        # Determine intent and obtain LLM reply synchronously (could be moved
        # to asyncio.to_thread if it becomes a bottleneck)
        intent = detect_intent(user_text)
        reply = _ask_groq(user_text)

        # Log the interaction to Excel
        row = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user_id": user.id,
            "username": user.username,
            "intent": intent,
            "message": user_text,
            "reply": reply,
        }
        _save_to_excel(row)

        # Send reply to user
        await update.message.reply_text(reply if reply else "⚠️ لم أتمكن من معالجة رسالتك.")
    except Exception as exc:
        # Catch any unexpected errors to avoid crashing the handler
        logger.exception("❌ handle_message error", exc_info=exc)
        await update.message.reply_text("⚠️ حدث خطأ أثناء معالجة رسالتك.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled errors from the dispatcher."""
    logger.exception("💥 Unhandled error", exc_info=context.error)


# ---------------------------------------------------------------------------
# Webhook cleanup


def close_webhook_sync(token: str, drop_pending: bool = True) -> None:
    """Synchronously delete the Telegram webhook associated with the bot.

    Since we are running the bot in polling mode, we must remove any
    previously configured webhook.  Telegram allows only one update delivery
    mechanism (webhook or polling) at a time; leaving a webhook set will
    cause conflicts when polling.  This function uses `requests` rather than
    the async Telegram API to perform the cleanup before the event loop
    starts.

    Args:
        token: The bot token.
        drop_pending: Whether to discard pending updates on the webhook.
    """
    try:
        url = f"https://api.telegram.org/bot{token}/deleteWebhook"
        data = {"drop_pending_updates": "true" if drop_pending else "false"}
        r = requests.post(url, data=data, timeout=10)
        try:
            payload = r.json()
        except Exception:
            payload = r.text
        logger.info(
            "🧹 deleteWebhook -> %s %s",
            r.status_code,
            payload,
        )
    except Exception as exc:
        logger.warning("⚠️ Could not delete webhook: %s", exc)


# ---------------------------------------------------------------------------
# Entry point


def main() -> None:
    """Entry point for the bot.  Configures and starts polling."""
    # Ensure only one instance runs on the host
    ensure_single_instance(8765)

    # Clear any existing webhook to avoid polling conflicts
    close_webhook_sync(BOT_TOKEN, drop_pending=True)

    # Build the application
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    app.add_error_handler(on_error)

    logger.info("✅ Bot is starting with Groq…")

    # Run the bot.  Capture Conflict errors to abort gracefully if another
    # process is polling the same token (e.g. on a remote server).
    try:
        app.run_polling(drop_pending_updates=True)
    except Conflict:
        logger.error(
            "❌ 409 Conflict: Another process is polling updates for this bot. "
            "Ensure only a single instance uses this BOT_TOKEN."
        )
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🔴 Bot stopped manually.")
