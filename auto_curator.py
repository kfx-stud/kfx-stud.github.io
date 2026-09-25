import os
import json
import uuid
import subprocess
from pathlib import Path
from PIL import Image
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 1. Загрузка переменных окружения из .env
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("Ошибка: Ключ GEMINI_API_KEY не найден в файле .env!")
    print("Создай файл .env рядом со скриптом и добавь: GEMINI_API_KEY=твой_ключ")
    exit(1)

# 2. Настройки путей и фильтра
BASE_DIR = Path(__file__).parent
INCOMING_DIR = BASE_DIR / "incoming"
IMAGES_DIR = BASE_DIR / "images"
DATA_FILE = BASE_DIR / "data.json"
SCORE_THRESHOLD = 7  # Минимальный балл (от 1 до 10) для добавления на сайт

client = genai.Client(api_key=API_KEY)

PROMPT = """
Ты эксперт по интернет-мемам и куратор смешных фото компании друзей.
Проанализируй изображение и верни результат СТРОГО в формате JSON без markdown-разметки:
{
  "score": <целое число от 1 до 10, где 1 - обычное скучное фото, а 10 - легендарный разрывной мем>,
  "tag": "<короткий тег на русском, например: Мем, Вайб, Крипи, Чилл, Стрит, Дистанционка, Аут>",
  "tag_class": "<одно из трех значений на выбор: '', 'purple', 'alt'>",
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
        try:
            cards = json.load(f)
        except json.JSONDecodeError:
            cards = []

    valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    incoming_files = [f for f in INCOMING_DIR.iterdir() if f.suffix.lower() in valid_extensions]

    if not incoming_files:
        print(f"В папке {INCOMING_DIR.name}/ нет новых файлов для анализа.")
        return

    added_count = 0

    for file_path in incoming_files:
        print(f"\n[+] Анализ файла: {file_path.name}")
        try:
            with Image.open(file_path) as img:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[img, PROMPT],
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                data = json.loads(response.text)

            score = int(data.get("score", 0))
            title = data.get("title", "Без названия")
            print(f"Вердикт нейросети: «{title}» | Оценка: {score}/10")

            if score >= SCORE_THRESHOLD:
                new_filename = f"photo_{uuid.uuid4().hex[:8]}.jpg"
                dest_path = IMAGES_DIR / new_filename

                # Оптимизация размера изображения для быстрой загрузки сайта
                with Image.open(file_path) as img:
                    img = img.convert("RGB")
                    img.thumbnail((1200, 1200))
                    img.save(dest_path, "JPEG", quality=85)

                new_card = {
                    "file": f"images/{new_filename}",
                    "tag": data.get("tag", "Вайб"),
                    "tag_class": data.get("tag_class", ""),
                    "title": title,
                    "caption": data.get("caption", "")
                }
                cards.insert(0, new_card)
                added_count += 1
                print(f"-> Добавлено в архив сайта: {new_filename}")
            else:
                print(f"-> Пропущено: балл {score} ниже порога {SCORE_THRESHOLD}")

            # Удаляем проверенное фото из incoming
            file_path.unlink()

        except Exception as e:
            print(f"Ошибка при обработке {file_path.name}: {e}")

    if added_count > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)

        print(f"\n[✓] Успешно добавлено карточек: {added_count}")
        print("Отправка изменений на GitHub...")

        try:
            subprocess.run(["git", "add", "images/", "data.json"], check=True)
            subprocess.run(["git", "commit", "-m", f"AI curator: добавлено {added_count} фото"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("Готово! Сайт обновится через несколько секунд.")
        except subprocess.CalledProcessError as e:
            print(f"Ошибка Git при коммите/пуше: {e}")
    else:
        print("\nНовых подходящих карточек не найдено. data.json не изменялся.")

if __name__ == "__main__":
    process_photos()
