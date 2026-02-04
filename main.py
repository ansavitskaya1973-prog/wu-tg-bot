# main.py
# WU Economics Tutor — Telegram bot + OpenAI Assistants API + Vector Store
# Шаг 3.1/3.2: UX-кнопки + команды + выбор языка кнопками (RU/DE)
#
# Команды:
# /start  — приветствие + меню
# /reset  — сброс диалога (новый thread)
# /lang   — выбор языка (inline-кнопки RU/DE)
#
# Кнопки (Reply keyboard):
# 🧭 Темы (Syllabus) | 🧠 Начать с нуля
# 🏋️ Тренировка      | 🎓 Мини-экзамен
# 🌍 Язык             | ♻️ Reset

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
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("wu_tg_bot")


# -------------------------------------------------
# Переменные окружения
# -------------------------------------------------
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

ASSISTANT_ID = os.getenv("ASSISTANT_ID")           # обязательно для ассистента
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID")     # здесь может быть не обязателен (оставляем как было)

if not TG_TOKEN:
    raise RuntimeError("Не найден TG_BOT_TOKEN в переменных окружения (.env)")
if not OPENAI_API_KEY:
    raise RuntimeError("Не найден OPENAI_API_KEY в переменных окружения (.env)")
if not ASSISTANT_ID:
    raise RuntimeError("Не найден ASSISTANT_ID в переменных окружения (.env)")

# -------------------------------------------------
# OpenAI client
# -------------------------------------------------
client = OpenAI(api_key=OPENAI_API_KEY)


# -------------------------------------------------
# UI: Reply Keyboard (нижние кнопки)
# -------------------------------------------------
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🧭 Темы (Syllabus)"), KeyboardButton("🧠 Начать с нуля")],
            [KeyboardButton("🏋️ Тренировка"), KeyboardButton("🎓 Мини-экзамен")],
            [KeyboardButton("🌍 Язык"), KeyboardButton("♻️ Reset")],
        ],
        resize_keyboard=True
    )


# -------------------------------------------------
# UI: Inline Keyboard для выбора языка
# -------------------------------------------------
def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang:ru"),
        InlineKeyboardButton("🇩🇪 Deutsch", callback_data="lang:de"),
    ]])


def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    # Язык по умолчанию — RU
    return context.user_data.get("lang", "ru")


def lang_instruction(lang: str) -> str:
    """
    ЖЁСТКОЕ ПРАВИЛО:
    - НИКАКОГО автоопределения языка.
    - НИКАКОГО переключения языка в процессе.
    - Если выбран DE — всё на немецком. Если выбран RU — всё на русском.
    """
    if lang == "de":
        return (
            "WICHTIG: Strikte Sprachregel.\n"
            "1) Antworte IMMER auf Deutsch.\n"
            "2) KEIN Auto-Detect, KEIN Sprachwechsel.\n"
            "3) Auch wenn der Nutzer Russisch schreibt, bleib auf Deutsch.\n"
            "4) Erkläre einfach, wie für eine/n 16-Jährige/n Anfänger/in.\n"
            "5) Wenn der Nutzer um eine andere Sprache bittet, lehne höflich ab und bleib auf Deutsch."
        )
    return (
        "ВАЖНО: Жёсткое правило языка.\n"
        "1) Отвечай ВСЕГДА на русском.\n"
        "2) НИКАКОГО автоопределения, НИКАКОГО переключения языка.\n"
        "3) Даже если пользователь пишет по-немецки — отвечай по-русски.\n"
        "4) Объясняй просто, как для 16-летнего новичка.\n"
        "5) Если пользователь просит другой язык — вежливо откажи и останься на русском."
    )


# -------------------------------------------------
# Thread management
# -------------------------------------------------
def get_or_create_thread_id(context: ContextTypes.DEFAULT_TYPE) -> str:
    thread_id = context.user_data.get("thread_id")
    if thread_id:
        return thread_id

    thread = client.beta.threads.create()
    context.user_data["thread_id"] = thread.id
    return thread.id


def reset_thread(context: ContextTypes.DEFAULT_TYPE) -> str:
    thread = client.beta.threads.create()
    context.user_data["thread_id"] = thread.id
    return thread.id


# -------------------------------------------------
# Assistants: run + polling
# -------------------------------------------------
def wait_for_run(thread_id: str, run_id: str, timeout_sec: int = 90) -> str:
    start = time.time()
    while True:
        run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
        status = run.status

        if status in ("completed", "failed", "cancelled", "expired"):
            return status

        if time.time() - start > timeout_sec:
            return status  # может быть in_progress

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
    # 1) user message
    client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=user_text
    )

    # 2) run (жёстко фиксируем язык через instructions)
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=ASSISTANT_ID,
        instructions=lang_instruction(lang),
    )

    status = wait_for_run(thread_id, run.id, timeout_sec=120)

    if status != "completed":
        # Сообщение тоже на выбранном языке (жёсткое правило UX)
        if lang == "de":
            return (
                "Ups 🙈 Ich konnte die Anfrage nicht abschließen.\n"
                f"Status: {status}\n"
                "Versuche es erneut oder schreibe /reset."
            )
        return (
            "Упс 🙈 Я не смог завершить обработку запроса.\n"
            f"Статус: {status}\n"
            "Попробуй ещё раз или напиши /reset."
        )

    answer = get_last_assistant_message(thread_id)
    if not answer:
        if lang == "de":
            return (
                "Ich habe kurz nachgedacht 🤔, aber die Antwort ist leer geblieben.\n"
                "Formuliere die Frage bitte anders."
            )
        return (
            "Я задумался 🤔, но ответ не сформировался.\n"
            "Попробуй переформулировать вопрос."
        )

    return answer


# -------------------------------------------------
# Команды
# -------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    if lang == "de":
        text = (
            "Hallo! 👋\n\n"
            "Ich bin der WU Economics Tutor.\n"
            "Ich erkläre Wirtschaft einfach und trainiere für die Aufnahmeprüfung.\n\n"
            "Sprache ist FEST eingestellt. Unten eine Taste wählen oder Frage schreiben 🙂"
        )
    else:
        text = (
            "Привет! 👋\n\n"
            "Я WU Economics Tutor.\n"
            "Объясняю экономику простым языком и готовлю к вступительному экзамену.\n\n"
            "Язык ответа фиксируется. Нажми кнопку внизу или задай вопрос 🙂"
        )

    await update.message.reply_text(text, reply_markup=main_menu_kb())


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reset_thread(context)
    lang = get_lang(context)
    if lang == "de":
        await update.message.reply_text("Fertig ✅ Neuer Dialog gestartet.", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text("Готово ✅ Я сбросил диалог и начал новый.", reply_markup=main_menu_kb())


async def lang_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # UX: показываем выбор кнопками
    await update.message.reply_text(
        "Выбери язык ответа бота / Wähle die Antwortsprache:",
        reply_markup=lang_keyboard()
    )


async def on_lang_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, lang = query.data.split(":", 1)  # "ru" | "de"
    context.user_data["lang"] = lang

    # Подтверждение можно оставить русским, но лучше тоже по выбранному:
    if lang == "de":
        await query.edit_message_text("✅ Sprache eingestellt: 🇩🇪 Deutsch (fest)")
    else:
        await query.edit_message_text("✅ Язык установлен: 🇷🇺 Русский (фиксированный)")


# -------------------------------------------------
# Быстрые режимы через кнопки
# -------------------------------------------------
def build_prompt_for_button(button_text: str, lang: str) -> Optional[str]:
    """
    ВАЖНО: DE = экзамен:
    - При выборе немецкого, "Мини-экзамен" запускаем как строгий экзамен на немецком.
    - В остальных кнопках можно оставлять команды, но текст-уточнение делаем под язык.
    """
    if lang == "de":
        if button_text == "🧭 Темы (Syllabus)":
            return "/syllabus Zeige die Struktur und Themen des Lehrbuchs. Nutze das Inhaltsverzeichnis als Kanon. Gib eine ausführliche Themenliste."
        if button_text == "🧠 Начать с нуля":
            return "/learn_easy Ich verstehe Wirtschaft gar nicht. Wo soll ich anfangen? Gib einen 7-Tage-Plan (10–15 Minuten pro Tag)."
        if button_text == "🏋️ Тренировка":
            return "/quiz Gib 5 Anfängerfragen zur ersten Thema. Nach jeder Frage warte auf meine Antwort."
        if button_text == "🎓 Мини-экзамен":
            # DE = экзамен (строгий режим)
            return (
                "/exam Strenger Mini-Test (Aufnahmeprüfung-Style), 10 Minuten, 5 Fragen. "
                "Zuerst NUR die Fragen, KEINE Lösungen, KEINE Hinweise. "
                "Ich antworte nacheinander."
            )
        return None

    # RU
    if button_text == "🧭 Темы (Syllabus)":
        return "/syllabus Покажи структуру и темы учебника. Используй оглавление как канон. Дай подробный список тем."
    if button_text == "🧠 Начать с нуля":
        return "/learn_easy Я ничего не понимаю в экономике. С чего начать? Дай план на 7 дней по 10–15 минут."
    if button_text == "🏋️ Тренировка":
        return "/quiz Дай 5 вопросов для новичка по первой теме. После каждого вопроса жди ответ."
    if button_text == "🎓 Мини-экзамен":
        return "/exam Сделай мини-экзамен на 10 минут: 5 вопросов. Сначала только вопросы, без ответов."
    return None


# -------------------------------------------------
# Обработка текста
# -------------------------------------------------
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.strip()

    # 1) кнопки меню
    if user_text == "♻️ Reset":
        reset_thread(context)
        lang = get_lang(context)
        if lang == "de":
            await update.message.reply_text("Fertig ✅ Neuer Dialog gestartet.", reply_markup=main_menu_kb())
        else:
            await update.message.reply_text("Готово ✅ Я сбросил диалог и начал новый.", reply_markup=main_menu_kb())
        return

    if user_text == "🌍 Язык":
        await update.message.reply_text(
            "Выбери язык ответа бота / Wähle die Antwortsprache:",
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
            answer = f"Упс 🙈 ошибка на стороне AI.\nТип: {e.__class__.__name__}"
        await update.message.reply_text(answer, reply_markup=main_menu_kb())
        return

    # 2) обычный вопрос
    thread_id = get_or_create_thread_id(context)

    try:
        answer = ask_assistant(thread_id, user_text, lang=lang)
    except Exception as e:
        logger.exception("Ошибка при обращении к OpenAI")
        answer = f"Упс 🙈 ошибка на стороне AI.\nТип: {e.__class__.__name__}"

    await update.message.reply_text(answer, reply_markup=main_menu_kb())


# -------------------------------------------------
# Точка входа
# -------------------------------------------------
def main():
    app = Application.builder().token(TG_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CommandHandler("lang", lang_cmd))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(on_lang_button, pattern=r"^lang:(ru|de)$"))

    # Текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("WU Economics Tutor запущен и слушает Telegram…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
