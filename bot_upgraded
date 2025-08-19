# -*- coding: utf-8 -*-
"""
Real Working Telegram Bot for جمعية حفظ النعمة (Hail Food Preservation Society)

New in this version:
- /links, /benefit, /theme, /dialect commands
- Intent routing with auto-inserted official links
- Hail (حايل) dialect is DEFAULT (users can toggle to فصحى with /dialect)
- Keeps: rate limiting, backups, health, stats, admin gating
"""
from dotenv import load_dotenv
load_dotenv()
import os
print(f"[DEBUG] BOT_TOKEN loaded: {os.getenv('BOT_TOKEN')}")



import logging
import threading
from datetime import datetime
from typing import Dict

import requests
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from bot_utils import detect_intent

from dotenv import load_dotenv
load_dotenv()

# --- Constants & links -------------------------------------------------------
EMPLOYMENT_URL = "https://khaier.us/login.jsf?id=683"          # التوظيف
VOLUNTEER_URL  = "https://nvg.gov.sa/"                          # التطوّع الوطني
BENEFICIARY_SIGNUP_URL = "https://khaier.app/auth/signup/683"   # تسجيل مستفيد جديد
BENEFICIARY_YT = "https://youtu.be/0zi63JgR_uM"                 # شرح فيديو

BENEFICIARY_REQUIREMENTS_BULLETS = [
    "الهوية الوطنية (صورة واضحة للوجهين).",
    "مشهد الحالة المالية.",
    "مشهد من الضمان الاجتماعي أو تعريف بالراتب (تقاعد/عمل/جهة أخرى) بحيث لا يتجاوز إجمالي الدخل 6000 ريال.",
    "إثبات السكن داخل نطاق حائل (صك ملكية/عقد إيجار من منصة إيجار/خطاب جهة العمل).",
    "اجتياز البحث الاجتماعي وموافقة اللجنة.",
    "أن يكون الطلب ضمن اختصاص الجمعية وخدماتها.",
]

# --- Imports from local project (with fallbacks) ------------------------------
try:
    from config import Config
    from utils import data_manager, rate_limiter, groq_client, detect_intent  # if available
    MODULES_AVAILABLE = True
except Exception as e:
    logging.warning("Some modules not available: %s", e)
    MODULES_AVAILABLE = False

# --- Logging -----------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("bot")

# --- Per-user preferences (in-memory) ----------------------------------------
# NOTE: For production, persist in your data store (DB/redis).
DEFAULT_HAIL_DIALECT = True  # << Hail dialect is default
user_pref: Dict[int, Dict[str, bool]] = {}  # {user_id: {"hail_dialect": bool}}

def get_use_hail_dialect(user_id: int) -> bool:
    # If user not seen before, return default
    return user_pref.get(user_id, {}).get("hail_dialect", DEFAULT_HAIL_DIALECT)

def toggle_hail_dialect(user_id: int) -> bool:
    cur = get_use_hail_dialect(user_id)
    user_pref.setdefault(user_id, {})["hail_dialect"] = not cur
    return not cur

# --- Small helpers ------------------------------------------------------------
def _wrap(text_fusha: str, text_hail: str, use_hail: bool) -> str:
    """Return text in dialect if enabled, else fusha."""
    return text_hail if use_hail else text_fusha

def mask_token(tok: str) -> str:
    if not tok or tok in ("NOT_SET",):
        return "NOT_SET"
    return tok[:10] + "..." if len(tok) > 13 else tok

def build_beneficiary_requirements_md() -> str:
    bullets = "\n".join(f"• {item}" for item in BENEFICIARY_REQUIREMENTS_BULLETS)
    return (
        "📄 **الشروط والمستندات المطلوبة:**\n"
        f"{bullets}\n\n"
        f"🎥 شرح فيديو: {BENEFICIARY_YT}"
    )

def detect_intent_simple(text: str) -> str:
    """Lightweight fallback intent detector if utils.detect_intent is not available."""
    t = (text or "").strip().lower()
    # Arabic keywords (basic)
    if any(k in t for k in ["تبرع", "طعام", "فائض"]):
        return "DONATION_FOOD"
    if any(k in t for k in ["مستفيد", "سلة", "مساعدة", "تسجيل"]):
        return "BENEFICIARY_REQUEST"
    if any(k in t for k in ["تطوع", "متطوع"]):
        return "VOLUNTEER_SIGNUP"
    if any(k in t for k in ["وظيفة", "وظايف", "عمل", "توظيف"]):
        return "EMPLOYMENT"
    return "OTHER"

# --- Bot ---------------------------------------------------------------------
class TelegramBot:
    def __init__(self):
        self.app = None
        self.is_running = False
        self._lock = threading.Lock()
        self.admin_ids = [123456789]  # TODO: replace with real admin IDs

        if MODULES_AVAILABLE:
            try:
                Config.validate()
                Config.create_directories()
            except Exception as e:
                logger.error("Configuration validation failed: %s", e)

    # --- Commands -------------------------------------------------------------
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        # Persist default for first-time users (optional but nice)
        user_pref.setdefault(u.id, {}).setdefault("hail_dialect", DEFAULT_HAIL_DIALECT)
        use_hail = get_use_hail_dialect(u.id)
        logger.info("START by @%s (%s), hail=%s", u.username, u.id, use_hail)

        text_fusha = (
            "👋 أهلاً بك! أنت تتحدث مع المساعد الرسمي **لجمعية حفظ النعمة بحائل**.\n\n"
            "الفئات: المتبرعون بفائض الطعام، المستفيدون، المتطوعون، والاستفسارات العامة.\n"
            "النطاق: مدينة حائل والمراكز التابعة لها.\n"
            "⏰ العمل: الأحد–الخميس 8:00ص–9:00م\n"
            "📞 تواصل/واتساب: 0551965445\n\n"
            "اكتب طلبك أو استخدم الأوامر:\n"
            "/help — قائمة الأوامر\n"
            "/links — روابط التوظيف/التطوع/التسجيل\n"
            "/benefit — شروط ومرفقات تسجيل المستفيد\n"
            "/dialect — تبديل الردود بين الفصحى ولهجة حايل"
        )
        text_hail = (
            "ياهلا والله! معك مساعد **جمعية حفظ النعمة بحايل** 👋\n\n"
            "نخدم: المتبرّعين، المستفيدين، المتطوّعين، وأي استفسار.\n"
            "نطاقنا: حايل والمراكز التابعة.\n"
            "⏰ الدوام: الأحد–الخميس 8:00 الصبح لـ 9:00 الليل\n"
            "📞 التواصل/واتساب: 0551965445\n\n"
            "اكتب وش تبي أو استخدم هالأوامر:\n"
            "/help — قائمة الأوامر\n"
            "/links — روابط التوظيف/التطوع/التسجيل\n"
            "/benefit — الشروط والمرفقات\n"
            "/dialect — تبديل بين الفصحى ولهجة حايل"
        )
        await update.message.reply_text(_wrap(text_fusha, text_hail, use_hail))

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        use_hail = get_use_hail_dialect(u.id)

        text_fusha = (
            "🤖 **الأوامر المتاحة:**\n"
            "/start — رسالة ترحيب\n"
            "/help — هذه القائمة\n"
            "/links — روابط مهمة (توظيف، تطوع، تسجيل مستفيد)\n"
            "/benefit — الشروط والمستندات لتسجيل مستفيد\n"
            "/health — فحص صحة البوت\n"
            "/stats — إحصائيات (مشرفين)\n"
            "/backup — نسخة احتياطية (مشرفين)\n"
            "/dialect — تبديل الفصحى/لهجة حايل"
        )
        text_hail = (
            "🤖 **الأوامر:**\n"
            "/start — ترحيب\n"
            "/help — هذي القائمة\n"
            "/links — روابط مهمّة (توظيف/تطوع/تسجيل)\n"
            "/benefit — الشروط والمرفقات\n"
            "/health — فحص البوت\n"
            "/stats — إحصائيات (للمشرفين)\n"
            "/backup — نسخة احتياطية (للمشرفين)\n"
            "/dialect — فصحى/حايل"
        )
        await update.message.reply_text(_wrap(text_fusha, text_hail, use_hail))

    async def links_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        use_hail = get_use_hail_dialect(u.id)
        text_fusha = (
            "🔗 **روابط مهمة:**\n"
            f"• التوظيف: {EMPLOYMENT_URL}\n"
            f"• التطوّع الوطني: {VOLUNTEER_URL}\n"
            f"• تسجيل مستفيد جديد: {BENEFICIARY_SIGNUP_URL}\n"
            f"• شرح فيديو للمستفيد: {BENEFICIARY_YT}"
        )
        text_hail = (
            "🔗 **روابط مهمّة:**\n"
            f"• التوظيف: {EMPLOYMENT_URL}\n"
            f"• التطوّع: {VOLUNTEER_URL}\n"
            f"• تسجيل مستفيد: {BENEFICIARY_SIGNUP_URL}\n"
            f"• فيديو الشرح: {BENEFICIARY_YT}"
        )
        await update.message.reply_text(_wrap(text_fusha, text_hail, use_hail), disable_web_page_preview=True)

    async def benefit_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        use_hail = get_use_hail_dialect(u.id)
        core = build_beneficiary_requirements_md()
        suffix_f = f"\n\n📝 للتسجيل الآن: {BENEFICIARY_SIGNUP_URL}"
        suffix_h = f"\n\n📝 للتسجيل الحين: {BENEFICIARY_SIGNUP_URL}"
        await update.message.reply_text(_wrap(core + suffix_f, core + suffix_h, use_hail), disable_web_page_preview=True)

    async def theme_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Re-send the service ‘theme’ (info block) quickly."""
        await self.start_command(update, context)

    async def dialect_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        new_state = toggle_hail_dialect(u.id)
        if new_state:
            await update.message.reply_text("✅ تم تفعيل **لهجة حايل** للردود. إذا ودك ترجع للفصحى أرسل /dialect")
        else:
            await update.message.reply_text("✅ تم الرجوع إلى **العربية الفصحى**. لتفعيل لهجة حايل أرسل /dialect")

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        if u.id not in self.admin_ids:
            await update.message.reply_text("⚠️ هذا الأمر للمشرفين فقط.")
            return
        if not MODULES_AVAILABLE:
            await update.message.reply_text("⚠️ وحدة إدارة البيانات غير متاحة.")
            return

        stats = data_manager.get_statistics()
        msg = (
            "📊 **إحصائيات البوت**\n\n"
            f"إجمالي الطلبات: {stats.get('total_requests', 0)}\n"
            f"طلبات اليوم: {stats.get('today_requests', 0)}\n\n"
            "توزيع النوايا:\n"
        )
        for k, v in (stats.get("intents", {}) or {}).items():
            msg += f"• {k}: {v}\n"
        msg += f"\n⏰ آخر تحديث: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        await update.message.reply_text(msg)

    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        u = update.effective_user
        if u.id not in self.admin_ids:
            await update.message.reply_text("⚠️ هذا الأمر للمشرفين فقط.")
            return
        if not MODULES_AVAILABLE:
            await update.message.reply_text("⚠️ وحدة إدارة البيانات غير متاحة.")
            return

        await update.message.reply_text("🔄 جاري إنشاء نسخة احتياطية...")
        path = data_manager.create_backup()
        await update.message.reply_text("✅ تم إنشاء النسخة الاحتياطية: {}".format(path) if path else "❌ فشل إنشاء النسخة.")

    async def health_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        checks = []
        # DB
        try:
            if MODULES_AVAILABLE:
                data_manager.get_statistics()
                checks.append("✅ قاعدة البيانات")
            else:
                checks.append("⚠️ وحدة إدارة البيانات غير متاحة")
        except Exception as e:
            checks.append(f"❌ قاعدة البيانات: {e}")

        # Groq
        try:
            if MODULES_AVAILABLE:
                ok = bool(groq_client.ask("ping"))
                checks.append("✅ Groq API" if ok else "⚠️ Groq API: لا يوجد رد")
            else:
                checks.append("⚠️ وحدة Groq غير متاحة")
        except Exception as e:
            checks.append(f"❌ Groq API: {e}")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"🏥 **حالة البوت**\n\n⏰ وقت السيرفر: {now}\n" + "\n".join(checks)
        if all(c.startswith("✅") for c in checks):
            msg += "\n\n🎉 البوت يعمل بشكل ممتاز"
        elif any(c.startswith("❌") for c in checks):
            msg += "\n\n⚠️ توجد مشاكل تتطلب انتباه"
        else:
            msg += "\n\nℹ️ يعمل مع بعض التحذيرات"
        await update.message.reply_text(msg)

    # --- Messages -------------------------------------------------------------
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        txt = (update.message.text or "").strip()
        if not txt:
            return

        # Rate limit
        if MODULES_AVAILABLE:
            try:
                if not rate_limiter.is_allowed(user.id):
                    await update.message.reply_text("⏳ رسايلك كثيرة ورا بعض، خلّنا نكمل خطوة خطوة—جاوب آخر سؤال فقط.")
                    return
            except Exception:
                pass

        # Intent (cleaned: direct try/except)
        try:
            intent = detect_intent(txt)  # if import failed, except below
        except Exception:
            intent = detect_intent_simple(txt)

        use_hail = get_use_hail_dialect(user.id)
        reply = None

        # Route intents with links + prompts
        if intent == "DONATION_FOOD":
            reply = _wrap(
                "🍱 شكرًا لتبرعك! فضلاً زوّدنا: الموقع بالتفصيل، نوع/كمية الطعام، الوقت المناسب للاستلام، ورقم التواصل.",
                "🍱 تسلّم! عطنا: موقع الاستلام، نوع/كمية الأكل، الوقت المناسب، ورقمك.",
                use_hail
            )
        elif intent == "BENEFICIARY_REQUEST":
            core = _wrap(
                "🤝 حياك الله لطلب المساعدة. يرجى تزويدنا: الاسم الثلاثي، الحي/الموقع، عدد أفراد الأسرة، الحالة/الدخل التقريبي، رقم التواصل.",
                "🤝 هلا والله، لطلب المساعدة عطنا: الاسم الثلاثي، الحي، عدد أفراد الأسرة، الحالة/الدخل التقريبي، ورقمك.",
                use_hail
            )
            links = f"\n\n📌 التسجيل: {BENEFICIARY_SIGNUP_URL}\n" + build_beneficiary_requirements_md()
            reply = core + "\n" + links
        elif intent == "VOLUNTEER_SIGNUP":
            reply = _wrap(
                f"🙌 ممتنين لرغبتك بالتطوع! سجّل عبر المنصة الوطنية: {VOLUNTEER_URL}\n"
                "واذكر لنا: الاسم، العمر، المهارات/التخصص، الأوقات المناسبة، رقم التواصل.",
                f"🙌 بيّض الله وجهك! سجّل بالتطوع عبر: {VOLUNTEER_URL}\n"
                "واذكر: اسمك، عمرك، مهاراتك، وقتك المناسب، ورقمك.",
                use_hail
            )
        elif intent == "EMPLOYMENT":
            reply = _wrap(
                f"💼 للتوظيف والتقديم على الوظائف الشاغرة يرجى الدخول على: {EMPLOYMENT_URL}",
                f"💼 لو ناوي تقدّم على وظيفة، هذا الرابط: {EMPLOYMENT_URL}",
                use_hail
            )
        else:
            # Fallback to LLM if available; else default hint
            if MODULES_AVAILABLE:
                try:
                    reply = groq_client.ask(txt) or _wrap(
                        "⚠️ لم أفهم طلبك تمامًا. هل تقصد تبرعًا، طلب مساعدة، أو تطوعًا؟ استخدم /help.",
                        "⚠️ ما فهمت زين.. تقصد تبرع، مساعدة، ولا تطوع؟ جرّب /help.",
                        use_hail
                    )
                except Exception:
                    reply = _wrap(
                        "⚠️ لم أفهم طلبك تمامًا. هل تقصد تبرعًا، طلب مساعدة، أو تطوعًا؟ استخدم /help.",
                        "⚠️ ما فهمت زين.. تبي تبرع، مساعدة، ولا تطوع؟ جرّب /help.",
                        use_hail
                    )
            else:
                reply = _wrap(
                    "👋 مرحبًا! البوت يعمل بوضع محدود. للتواصل: 0551965445",
                    "👋 حيّاك! البوت بوضع محدود. للتواصل: 0551965445",
                    use_hail
                )

        # Save to storage (best-effort)
        if MODULES_AVAILABLE:
            try:
                row = {
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "user_id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "intent": intent,
                    "message": txt,
                    "reply": reply,
                }
                data_manager.save_to_excel(row)
            except Exception as e:
                logger.warning("Saving failed: %s", e)

        await update.message.reply_text(reply, disable_web_page_preview=True)

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Unhandled error", exc_info=context.error)

    # --- Internal -------------------------------------------------------------
    def close_webhook_sync(self, token: str, drop_pending: bool = True) -> None:
        try:
            url = f"https://api.telegram.org/bot{token}/deleteWebhook"
            data = {"drop_pending_updates": "true" if drop_pending else "false"}
            r = requests.post(url, data=data, timeout=30)
            try:
                payload = r.json()
            except Exception:
                payload = r.text
            logger.info("deleteWebhook -> %s %s", r.status_code, payload)
        except Exception as e:
            logger.warning("Could not delete webhook: %s", e)

    def setup_handlers(self) -> None:
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("links", self.links_command))
        self.app.add_handler(CommandHandler("benefit", self.benefit_command))
        self.app.add_handler(CommandHandler("theme", self.theme_command))
        self.app.add_handler(CommandHandler("dialect", self.dialect_command))
        self.app.add_handler(CommandHandler("stats", self.stats_command))
        self.app.add_handler(CommandHandler("backup", self.backup_command))
        self.app.add_handler(CommandHandler("health", self.health_command))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        self.app.add_error_handler(self.error_handler)

    # --- Run ------------------------------------------------------------------
    def run(self) -> None:
        try:
            bot_token = getattr(Config, "BOT_TOKEN", "NOT_SET") if MODULES_AVAILABLE else "NOT_SET"
            groq_key  = getattr(Config, "GROQ_API_KEY", "NOT_SET") if MODULES_AVAILABLE else "NOT_SET"

            # Clear error if token missing (friendlier message)
            if not bot_token or bot_token in ("NOT_SET", "your_bot_token_here"):
                raise RuntimeError("BOT_TOKEN is not set. Put it in .env or environment variables.")

            logger.info("Starting bot -> BOT=%s, GROQ=%s", mask_token(bot_token), mask_token(groq_key))

            if bot_token != "NOT_SET":
                self.close_webhook_sync(bot_token, drop_pending=True)

            self.app = ApplicationBuilder().token(bot_token).build()
            self.setup_handlers()

            logger.info("Polling ...")
            self.is_running = True
            self.app.run_polling(drop_pending_updates=True)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
        except Exception as e:
            logger.error("Startup failed: %s", e)
            raise
        finally:
            self.is_running = False


def main():
    bot = TelegramBot()
    bot.run()

if __name__ == "__main__":
    main()
