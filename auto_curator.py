import os
import json
import time
import uuid
import base64
import subprocess
from pathlib import Path
from PIL import Image
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    print("Ошибка: Ключ GEMINI_API_KEY не найден в файле .env!")
    exit(1)

API_KEY = API_KEY.strip()

BASE_DIR = Path(__file__).parent
INCOMING_DIR = BASE_DIR / "incoming"
IMAGES_DIR = BASE_DIR / "images"
DATA_FILE = BASE_DIR / "data.json"
SCORE_THRESHOLD = 7

PROMPT = """
Ты эксперт по интернет-мемам и куратор смешных фото компании друзей.
Проанализируй изображение и верни результат СТРОГО в формате JSON без markdown:
{
  "score": <целое число от 1 до 10, где 1 - скучное фото, а 10 - легендарный мем>,
  "tag": "<короткий тег на русском, например: Мем, Вайб, Крипи, Чилл, Стрит, Дистанционка, Аут>",
  "tag_class": "<одно из трех значений: '', 'purple', 'alt'>",
  "title": "<емкое смешное название карточки на русском, 2-3 слова>",
  "caption": "<остроумная ироничная подпись к фото на русском, 1-2 предложения>"
}
"""

def analyze_image_with_gemini(image_path: Path, max_retries=3):
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    b64_image = base64.b64encode(img_bytes).decode("utf-8")
    ext = image_path.suffix.lower()
    mime_type = "image/png" if ext == ".png" else "image/jpeg"

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={API_KEY}"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": API_KEY
    }
    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": mime_type, "data": b64_image}}
            ]
        }],
        "generationConfig": {
            "response_mime_type": "application/json"
        }
    }

    for attempt in range(1, max_retries + 1):
        res = requests.post(url, headers=headers, json=payload, timeout=60)
        if res.status_code == 200:
            result_json = res.json()
            text = result_json["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text)
        elif res.status_code in (429, 503):
            wait_time = attempt * 4
            print(f"Сервер занят ({res.status_code}). Повтор через {wait_time} сек... (попытка {attempt}/{max_retries})")
            time.sleep(wait_time)
        else:
            raise Exception(f"HTTP {res.status_code}: {res.text}")

    raise Exception("Превышено количество попыток запроса к API.")

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
    incoming_files = [
        f for f in INCOMING_DIR.iterdir()
        if f.suffix.lower() in valid_extensions and not f.name.endswith("_thumb.jpg")
    ]

    # Сразу удаляем мусорные миниатюры _thumb
    for thumb in INCOMING_DIR.glob("*_thumb.*"):
        try:
            thumb.unlink()
        except Exception:
            pass

    if not incoming_files:
        print(f"В папке {INCOMING_DIR.name}/ нет новых файлов.")
        return

    added_count = 0

    for file_path in incoming_files:
        print(f"\n[+] Анализ файла: {file_path.name}")
        try:
            data = analyze_image_with_gemini(file_path)

            score = int(data.get("score", 0))
            title = data.get("title", "Без названия")
            print(f"Вердикт нейросети: «{title}» | Оценка: {score}/10")

            if score >= SCORE_THRESHOLD:
                new_filename = f"photo_{uuid.uuid4().hex[:8]}.jpg"
                dest_path = IMAGES_DIR / new_filename

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

            file_path.unlink()
            time.sleep(2)  # Небольшая пауза между запросами

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