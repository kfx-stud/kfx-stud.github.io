import os
import json
import time
import uuid
import base64
import hashlib
import subprocess
from pathlib import Path
from PIL import Image
import requests
from dotenv import load_dotenv

load_dotenv()

raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY")
if not raw_keys:
    print("Ошибка: Ключи не найдены в файле .env!")
    print("Укажи в .env: GEMINI_API_KEYS=ключ1,ключ2,ключ3")
    exit(1)

API_KEYS = [k.strip() for k in raw_keys.split(",") if k.strip()]

class KeyManager:
    def __init__(self, keys):
        self.keys = keys
        self.current_idx = 0
        self.exhausted_keys = set()

    def get_current_key(self):
        if len(self.exhausted_keys) >= len(self.keys):
            return None
        return self.keys[self.current_idx]

    def mark_current_exhausted(self, reason="Лимит исчерпан"):
        key = self.keys[self.current_idx]
        masked = f"{key[:6]}...{key[-4:]}"
        print(f"[-] Ключ {masked} отключен: {reason}")
        self.exhausted_keys.add(key)
        self.switch_to_next()

    def switch_to_next(self):
        start_idx = self.current_idx
        while True:
            self.current_idx = (self.current_idx + 1) % len(self.keys)
            next_key = self.keys[self.current_idx]
            if next_key not in self.exhausted_keys:
                masked = f"{next_key[:6]}...{next_key[-4:]}"
                print(f"[+] Переключение на ключ: {masked}")
                return
            if self.current_idx == start_idx:
                break

key_manager = KeyManager(API_KEYS)

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

def get_file_hash(file_path: Path) -> str:
    """Вычисляет SHA-256 хеш файла для точного поиска дубликатов."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def get_existing_hashes(cards: list) -> set:
    """Собирает хеши уже опубликованных фото из data.json и папки images/."""
    hashes = set()
    for card in cards:
        if "hash" in card:
            hashes.add(card["hash"])
        else:
            img_rel_path = card.get("file")
            if img_rel_path:
                img_path = BASE_DIR / img_rel_path
                if img_path.exists():
                    h = get_file_hash(img_path)
                    card["hash"] = h
                    hashes.add(h)
    return hashes

def analyze_image_with_gemini(image_path: Path):
    with open(image_path, "rb") as f:
        img_bytes = f.read()

    b64_image = base64.b64encode(img_bytes).decode("utf-8")
    ext = image_path.suffix.lower()
    mime_type = "image/png" if ext == ".png" else "image/jpeg"

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

    while True:
        current_key = key_manager.get_current_key()
        if not current_key:
            raise Exception("Все доступные API-ключи исчерпали свои суточные лимиты!")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent?key={current_key}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": current_key
        }

        try:
            res = requests.post(url, headers=headers, json=payload, timeout=60)
            
            if res.status_code == 200:
                result_json = res.json()
                text = result_json["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)

            elif res.status_code in (429, 401, 403):
                key_manager.mark_current_exhausted(f"HTTP {res.status_code}")
                continue

            elif res.status_code == 503:
                print("Сервер временно занят (503). Пауза 8 сек...")
                time.sleep(8)
                continue

            else:
                raise Exception(f"HTTP {res.status_code}: {res.text}")

        except requests.exceptions.RequestException as e:
            print(f"Сетевой сбой: {e}. Пауза 5 сек...")
            time.sleep(5)

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

    # Предзагрузка базы хешей уже опубликованных фото
    existing_hashes = get_existing_hashes(cards)

    # Удаление миниатюр Telegram
    for thumb in INCOMING_DIR.glob("*_thumb.*"):
        try:
            thumb.unlink()
        except Exception:
            pass

    valid_extensions = {".jpg", ".jpeg", ".png", ".webp"}
    incoming_files = [
        f for f in INCOMING_DIR.iterdir()
        if f.suffix.lower() in valid_extensions and not f.name.endswith("_thumb.jpg")
    ]

    if not incoming_files:
        print(f"В папке {INCOMING_DIR.name}/ нет новых файлов.")
        return

    total_files = len(incoming_files)
    print(f"Загружено ключей: {len(API_KEYS)}")
    print(f"Найдено файлов для обработки: {total_files}")
    added_count = 0

    for idx, file_path in enumerate(incoming_files, start=1):
        print(f"\n[{idx}/{total_files}] Проверка файла: {file_path.name}")

        # Проверка на дубликат по хешу
        file_hash = get_file_hash(file_path)
        if file_hash in existing_hashes:
            print("-> [ДУБЛИКАТ] Это фото уже есть на сайте! Удаляем из incoming без вызова API.")
            file_path.unlink()
            continue

        try:
            data = analyze_image_with_gemini(file_path)
        except Exception as e:
            print(f"[-] Не удалось проанализировать {file_path.name}: {e}")
            print("-> Файл ОСТАВЛЕН в incoming.")
            if not key_manager.get_current_key():
                print("\n[!] Остановка: закончились все рабочие ключи.")
                break
            continue

        try:
            score = int(data.get("score", 0))
            title = data.get("title", "Без названия")
            print(f"Вердикт: «{title}» | Оценка: {score}/10")

            if score >= SCORE_THRESHOLD:
                new_filename = f"photo_{uuid.uuid4().hex[:8]}.jpg"
                dest_path = IMAGES_DIR / new_filename

                with Image.open(file_path) as img:
                    img = img.convert("RGB")
                    img.thumbnail((1200, 1200))
                    img.save(dest_path, "JPEG", quality=85)

                # Сохраняем хеш оптимизированного фото и оригинала
                saved_hash = get_file_hash(dest_path)
                existing_hashes.add(file_hash)
                existing_hashes.add(saved_hash)

                new_card = {
                    "file": f"images/{new_filename}",
                    "hash": saved_hash,
                    "tag": data.get("tag", "Вайб"),
                    "tag_class": data.get("tag_class", ""),
                    "title": title,
                    "caption": data.get("caption", "")
                }
                cards.insert(0, new_card)
                added_count += 1
                print(f"-> Добавлено в архив: {new_filename}")
                file_path.unlink()
            else:
                print(f"-> Пропущено: балл {score} ниже порога {SCORE_THRESHOLD}")
                file_path.unlink()

        except Exception as e:
            print(f"[-] Ошибка при обработке/сохранении {file_path.name}: {e}")
            print("-> Файл ОСТАВЛЕН в incoming.")

        if idx < total_files:
            time.sleep(3)

    if added_count > 0:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)

        print(f"\n[✓] Успешно добавлено новых карточек: {added_count}")
        print("Отправка изменений на GitHub...")

        try:
            subprocess.run(["git", "add", "images/", "data.json"], check=True)
            subprocess.run(["git", "commit", "-m", f"AI curator: добавлено {added_count} фото"], check=True)
            subprocess.run(["git", "push"], check=True)
            print("Готово! Сайт обновится через 30–60 секунд.")
        except subprocess.CalledProcessError as e:
            print(f"Ошибка Git при коммите/пуше: {e}")
    else:
        print("\nНовых карточек не добавлено. data.json не изменялся.")

if __name__ == "__main__":
    process_photos()