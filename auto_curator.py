import os
import json
import uuid
import subprocess
from pathlib import Path
from PIL import Image
from google import genai
from google.genai import types

# Конфигурация
GEMINI_API_KEY = "AQ.Ab8RN6KWKbzBmQ7F99vOUmBaZ4a2CgH3uXTL4NFJeLyOPd5u0w"
INCOMING_DIR = Path("incoming")
IMAGES_DIR = Path("images")
DATA_FILE = Path("data.json")
SCORE_THRESHOLD = 7  # Минимальный балл смеха/интереса от 1 до 10

client = genai.Client(api_key=GEMINI_API_KEY)

PROMPT = """
Ты эксперт по интернет-мемам и куратор забавных фотографий компании друзей.
Оцени это фото. Выведи результат СТРОГО в виде валидного JSON без markdown:
{
  "score": <число от 1 до 10, где 1 - обычное скучное фото, а 10 - легендарный мем>,
  "tag": "<короткий тег на русском, например: Мем, Вайб, Крипи, Чилл, Стрит, Дистанционка>",
  "tag_class": "<одно из трех значений: '', 'purple', 'alt'>",
  "title": "<емкое смешное название карточки на русском, 2-3 слова>",
  "caption": "<остроумная ироничная подпись к фото на русском, 1-2 предложения>"
}
"""

def process_photos():
    INCOMING_DIR.mkdir(exist_ok=True)
    IMAGES_DIR.mkdir(exist_ok=True)

    if not DATA_FILE.exists():
        DATA_FILE.write_text("[]", encoding="utf-8")

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        cards = json.load(f)

    extensions = {".jpg", ".jpeg", ".png", ".webp"}
    incoming_files = [f for f in INCOMING_DIR.iterdir() if f.suffix.lower() in extensions]

    if not incoming_files:
        print("В папке incoming/ нет новых фотографий.")
        return

    added_count = 0

    for file_path in incoming_files:
        print(f"Анализ {file_path.name}...")
        try:
            with Image.open(file_path) as img:
                # Отправка в нейросеть
                response = client.models.generate_content(
                    model="gemini-1.5-flash",
                    contents=[img, PROMPT],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                data = json.loads(response.text)

            score = data.get("score", 0)
            print(f"Результат: {data.get('title')} (Балл: {score}/10)")

            if score >= SCORE_THRESHOLD:
                # Генерируем уникальное имя файла
                new_filename = f"photo_{uuid.uuid4().hex[:8]}.jpg"
                dest_path = IMAGES_DIR / new_filename

                # Оптимизация и сохранение в images/
                with Image.open(file_path) as img:
                    img = img.convert("RGB")
                    img.thumbnail((1200, 1200))
                    img.save(dest_path, "JPEG", quality=85)

                # Добавление в начало списка карточек
                new_card = {
                    "file": f"images/{new_filename}",
                    "tag": data.get("tag", "Вайб"),
                    "tag_class": data.get("tag_class", ""),
                    "title": data.get("title", "Кадр"),
                    "caption": data.get("caption", "")
                }
                cards.insert(0, new_card)
                added_count += 1
                print(f"Принято на сайт: {new_filename}")
            else:
                print(f"Отклонено (слишком низкий балл: {score})")

            # Удаляем проверенное фото из incoming
            file_path.unlink()

        except Exception as e:
            print(f"Ошибка при обработке {file_path.name}: {e}")

    if added_count > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)

        # Автоматическая отправка в GitHub
        print("Отправка обновлений на GitHub...")
        subprocess.run(["git", "add", "images/", "data.json"])
        subprocess.run(["git", "commit", "-m", f"AI curator: добавлено {added_count} новых фото"])
        subprocess.run(["git", "push"])
        print("Готово! Сайт обновится в течение минуты.")

if __name__ == "__main__":
    process_photos()
