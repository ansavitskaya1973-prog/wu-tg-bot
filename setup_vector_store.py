import os
from dotenv import load_dotenv

load_dotenv()

from openai import OpenAI

# -----------------------------
# Настройки
# -----------------------------
VECTOR_STORE_NAME = "WU Economics Tutor (2026 canon + 2025 + Studienkolleg)"

# Файлы, которые нужно загрузить
FILES = [
    "Wirtschaft_verstehen_Aufnahmeprüfung_2026.pdf",  # КАНОН
    "Wirtschaft_verstehen_2025.pdf",                  # вспомогательный
    "Konspekt1.pdf",                                  # упрощение/тренировка
    "Konspekt2.pdf",                                  # упрощение/тренировка
]

# -----------------------------
# Проверки окружения
# -----------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Не найден OPENAI_API_KEY в .env")

client = OpenAI(api_key=OPENAI_API_KEY)

def main():
    # 1) Проверим, что файлы реально лежат рядом
    missing = [f for f in FILES if not os.path.exists(f)]
    if missing:
        raise RuntimeError(
            "Не найдены файлы:\n- " + "\n- ".join(missing) +
            "\n\nПоложи их в папку проекта (рядом с setup_vector_store.py) "
            "или поправь список FILES."
        )

    print("✅ Файлы найдены. Создаю Vector Store...")

    # 2) Создаём Vector Store
    vector_store = client.vector_stores.create(name=VECTOR_STORE_NAME)
    print(f"✅ Vector Store создан: {vector_store.id}")

    # 3) Загружаем файлы пачкой и ждём индексации
    print("⏳ Загружаю файлы и жду индексации (это может занять пару минут)...")

    file_streams = [open(p, "rb") for p in FILES]
    try:
        # upload_and_poll — самый удобный способ: загрузит и дождётся обработки
        file_batch = client.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vector_store.id,
            files=file_streams,
        )
    finally:
        for fs in file_streams:
            try:
                fs.close()
            except Exception:
                pass

    # 4) Результат
    print("\n✅ Готово!")
    print("VECTOR_STORE_ID =", vector_store.id)
    print("Статус batch:", getattr(file_batch, "status", "unknown"))
    counts = getattr(file_batch, "file_counts", None)
    if counts:
        print("file_counts:", counts)

    print("\n➡️ Скопируй VECTOR_STORE_ID и добавь в .env строку:")
    print(f"VECTOR_STORE_ID={vector_store.id}")

if __name__ == "__main__":
    main()
