# main.py
# WU Economics Tutor — Telegram bot + OpenAI Assistants API + Vector Store
# Версия с кнопкой Полный разбор
#
# Команды:
# /start  — приветствие + меню
# /reset  — сброс диалога (новый thread)
# /lang   — выбор языка (inline-кнопки RU/DE)
#
# Кнопки (Reply keyboard):
# Темы (Syllabus) | Начать с нуля
# Тренировка      | Мини-экзамен
# Полный разбор   | Язык
# Reset


from dotenv import load_dotenv
load_dotenv()


import os
import time
import logging
from typing import Optional


from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


from openai import OpenAI


# -------------------------------------------------
# Логирование
# -------------------------------------------------
logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# -------------------------------------------------
# Переменные окружения
# -------------------------------------------------
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
if not TG_TOKEN:
        raise RuntimeError("Не найден TG_BOT_TOKEN в переменных окружения (.env)")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")

if not OPENAI_API_KEY:
        raise RuntimeError("Не найден OPENAI_API_KEY в переменных окружения (.env)")
    if not ASSISTANT_ID:
            raise RuntimeError("Не найден ASSISTANT_ID в переменных окружения (.env)")

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------------------------------
# Thread management
# -------------------------------------------------
def get_or_create_thread_id(context: ContextTypes.DEFAULT_TYPE) -> str:
        if "thread_id" not in context.user_data:
                    thread = client.beta.threads.create()
                    context.user_data["thread_id"] = thread.id
                    logger.info(f"Создан новый thread: {thread.id}")
                return context.user_data["thread_id"]


def reset_thread(context: ContextTypes.DEFAULT_TYPE):
        thread = client.beta.threads.create()
    context.user_data["thread_id"] = thread.id
    logger.info(f"Thread сброшен, новый: {thread.id}")


# -------------------------------------------------
# UI: Reply Keyboard (главное меню)
# -------------------------------------------------
def main_menu_kb() -> ReplyKeyboardMarkup:
        return ReplyKeyboardMarkup(
            [
                            [KeyboardButton("\U0001f9ed Темы (Syllabus)"), KeyboardButton("\U0001f9e0 Начать с нуля")],
                            [KeyboardButton("\U0001f3cb\ufe0f Тренировка"), KeyboardButton("\U0001f393 Мини-экзамен")],
                            [KeyboardButton("\U0001f4d8 Полный разбор"), KeyboardButton("\U0001f30d Язык")],
                            [KeyboardButton("\u267b\ufe0f Reset")],
            ],
            resize_keyboard=True
)


# -------------------------------------------------
# UI: Inline Keyboard для выбора языка
# -------------------------------------------------
def lang_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("\U0001f1f7\U0001f1fa Русский", callback_data="lang:ru"),
            InlineKeyboardButton("\U0001f1e9\U0001f1ea Deutsch", callback_data="lang:de"),
]])


def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
        return context.user_data.get("lang", "ru")


def lang_instruction(lang: str) -> str:
        if lang == "de":
                    return (
                                    "WICHTIG: Strikte Sprachregel.\n"
                                    "1) Antworte IMMER auf Deutsch.\n"
                                    "2) KEIN Auto-Detect, KEIN Sprachwechsel.\n"
                                    "3) Auch wenn der Nutzer Russisch schreibt, bleib auf Deutsch.\n"
                                    "4) Stil: B2-Niveau, akademisch, wie bei der Aufnahmeprüfung WU.\n"
                                    "5) Keine Smileys, keine Motivationsfloskeln."
                    )
else:
        return (
                        "ВАЖНО: Жёсткое языковое правило.\n"
                        "1) Отвечай ВСЕГДА на русском языке.\n"
                        "2) НИКАКОГО автоопределения языка.\n"
                        "3) Даже если пользователь пишет на немецком или другом языке — отвечай на русском.\n"
                        "4) Стиль: понятный, образовательный, нейтральный.\n"
                        "5) Без смайликов и мотивационных фраз."
        )


# -------------------------------------------------
# OpenAI: ожидание завершения run
# -------------------------------------------------
def wait_for_run(thread_id: str, run_id: str, timeout_sec: int = 90) -> str:
        start = time.time()
        while True:
                    run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
                    status = run.status

            if status in ("completed", "failed", "cancelled", "expired"):
                            return status

        if time.time() - start > timeout_sec:
                        return status

        time.sleep(0.7)


def get_last_assistant_message(thread_id: str) -> str:
        msgs = client.beta.threads.messages.list(thread_id=thread_id, limit=10)
    for m in msgs.data:
                if m.role == "assistant":
                                parts = []
                                for c in m.content:
                                                    if getattr(c, "type", None) == "text":
                                                                            parts.append(c.text.value)
                                                                    text = "\n".join(parts).strip()
                                                return text
                        return ""


def ask_assistant(thread_id: str, user_text: str, lang: str = "ru") -> str:
        client.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=user_text
        )

    run = client.beta.threads.runs.create(
                thread_id=thread_id,
                assistant_id=ASSISTANT_ID,
                instructions=lang_instruction(lang),
    )

    status = wait_for_run(thread_id, run.id, timeout_sec=120)

    if status != "completed":
                if lang == "de":
                                return (
                                                    "Die Anfrage konnte nicht abgeschlossen werden.\n"
                                                    f"Status: {status}\n"
                                                    "Bitte versuche es erneut."
                                )
else:
            return (
                                "Не удалось получить ответ.\n"
                                f"Статус: {status}\n"
                                "Попробуй ещё раз."
            )

    return get_last_assistant_message(thread_id)


# -------------------------------------------------
# Быстрые режимы через кнопки
# -------------------------------------------------
def build_prompt_for_button(button_text: str, lang: str) -> Optional[str]:
        if lang == "de":
                    if button_text == "\U0001f9ed Темы (Syllabus)":
                                    return "/syllabus Zeige die Struktur und Themen des Lehrbuchs. Nutze das Inhaltsverzeichnis als Kanon. Gib eine ausführliche Themenliste."
                                if button_text == "\U0001f9e0 Начать с нуля":
                                                return "/learn_easy Ich verstehe Wirtschaft gar nicht. Wo soll ich anfangen? Gib einen 7-Tage-Plan (10-15 Minuten pro Tag)."
                                            if button_text == "\U0001f3cb\ufe0f Тренировка":
                                                            return "/quiz Gib 5 Anfängerfragen zur ersten Thema. Nach jeder Frage warte auf meine Antwort."
                                                        if button_text == "\U0001f393 Мини-экзамен":
                                                                        return (
                                                                                            "/exam Strenger Mini-Test (Aufnahmeprüfung WU-Stil): "
                                                                                            "5 Fragen, kein Coaching, keine Tipps. "
                                                                                            "Erst nach allen Antworten Auswertung."
                                                                        )
                                                                    if button_text == "\U0001f4d8 Полный разбор":
                                                                                    return (
                                                                                                        "Vollständige Erklärung: Nenne das Thema oder Kapitel, "
                                                                                                        "das du vollständig verstehen möchtest. "
                                                                                                        "Ich erkläre den gesamten Stoff Schritt für Schritt, ohne Auslassungen."
                                                                                        )
else:
        if button_text == "\U0001f9ed Темы (Syllabus)":
                        return "/syllabus Покажи структуру и темы учебника. Используй оглавление как канон. Дай подробный список тем."
                    if button_text == "\U0001f9e0 Начать с нуля":
                                    return "/learn_easy Я ничего не понимаю в экономике. С чего начать? Дай план на 7 дней по 10-15 минут."
                                if button_text == "\U0001f3cb\ufe0f Тренировка":
                                                return "/quiz Дай 5 вопросов для новичка по первой теме. После каждого вопроса жди ответ."
                                            if button_text == "\U0001f393 Мини-экзамен":
                                                            return "/exam Сделай мини-экзамен на 10 минут: 5 вопросов. Сначала только вопросы, без ответов."
                                                        if button_text == "\U0001f4d8 Полный разбор":
                                                                        return (
                                                                                            "Полный разбор: напиши тему или главу, которую хочешь разобрать полностью — "
                                                                                            "я изложу весь материал последовательно, без пропусков, "
                                                                                            "без коротких определений. Структура: определение, механизм, логика, вывод."
                                                                        )
                                                                return None


# -------------------------------------------------
# Handlers
# -------------------------------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = get_lang(context)
    get_or_create_thread_id(context)

    if lang == "de":
                text = (
                                "Willkommen beim WU Tutor!\n\n"
                                "Ich helfe dir bei der Vorbereitung auf die Aufnahmeprüfung WU Vienna.\n\n"
                                "Wähle eine Option aus dem Menü oder stelle direkt eine Frage."
                )
else:
        text = (
                        "Добро пожаловать в WU Tutor!\n\n"
                        "Я помогу тебе подготовиться к вступительному экзамену по экономике "
                        "в Венский университет экономики (WU Vienna).\n\n"
                        "Выбери раздел в меню или задай вопрос напрямую."
        )

    await update.message.reply_text(text, reply_markup=main_menu_kb())


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
        reset_thread(context)
    lang = get_lang(context)
    if lang == "de":
                await update.message.reply_text("Neuer Dialog gestartet.", reply_markup=main_menu_kb())
else:
        await update.message.reply_text("Диалог сброшен. Начинаем заново.", reply_markup=main_menu_kb())


async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
        lang = get_lang(context)
    current = "\U0001f1f7\U0001f1fa Русский" if lang == "ru" else "\U0001f1e9\U0001f1ea Deutsch"
    await update.message.reply_text(
                f"Текущий язык / Aktuelle Sprache: {current}\n\nВыбери язык / Sprache wählen:",
                reply_markup=lang_keyboard()
    )


async def on_lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
    await query.answer()

    _, lang = query.data.split(":", 1)
    context.user_data["lang"] = lang

    if lang == "de":
                await query.edit_message_text("Sprache eingestellt: \U0001f1e9\U0001f1ea Deutsch (fest)")
else:
        await query.edit_message_text("Язык установлен: \U0001f1f7\U0001f1fa Русский (фиксированный)")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_text = update.message.text.strip()

    if user_text == "\u267b\ufe0f Reset":
                reset_thread(context)
        lang = get_lang(context)
        if lang == "de":
                        await update.message.reply_text("Neuer Dialog gestartet.", reply_markup=main_menu_kb())
        else:
            await update.message.reply_text("Готово. Начинаем заново.", reply_markup=main_menu_kb())
        return

    if user_text == "\U0001f30d Язык":
                lang = get_lang(context)
        current = "\U0001f1f7\U0001f1fa Русский" if lang == "ru" else "\U0001f1e9\U0001f1ea Deutsch"
        await update.message.reply_text(
                        f"Текущий язык / Aktuelle Sprache: {current}\n\nВыбери язык / Sprache wählen:",
                        reply_markup=lang_keyboard()
        )
        return

    lang = get_lang(context)

    btn_prompt = build_prompt_for_button(user_text, lang)
    if btn_prompt:
                thread_id = get_or_create_thread_id(context)
        try:
                        answer = ask_assistant(thread_id, btn_prompt, lang=lang)
        except Exception as e:
            logger.exception("Ошибка при обращении к OpenAI")
            answer = f"Ошибка AI: {e.__class__.__name__}"
        await update.message.reply_text(answer, reply_markup=main_menu_kb())
        return

    # обычный вопрос
    thread_id = get_or_create_thread_id(context)

    try:
                answer = ask_assistant(thread_id, user_text, lang=lang)
except Exception as e:
        logger.exception("Ошибка при обращении к OpenAI")
        answer = f"Ошибка AI: {e.__class__.__name__}"

    await update.message.reply_text(answer, reply_markup=main_menu_kb())


# -------------------------------------------------
# Точка входа
# -------------------------------------------------
def main():
        app = Application.builder().token(TG_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("lang", cmd_lang))
    app.add_handler(CallbackQueryHandler(on_lang_button, pattern=r"^lang:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Бот запущен.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
        main()
