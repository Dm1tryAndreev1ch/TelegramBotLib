#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import io
import sys
import time
import json
import shutil
import asyncio
import logging
import datetime
from typing import Optional, Dict, Any
from logging.handlers import TimedRotatingFileHandler

import requests
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse

# Пакет для работы с PostgreSQL
try:
    import psycopg2
    import psycopg2.extras
except Exception as e:
    psycopg2 = None  # Если не установлен, функции БД будут валиться с понятным логом

# ---------------------------
# Configuration (environment)
# ---------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not TELEGRAM_BOT_TOKEN:
    print("WARNING: TELEGRAM_BOT_TOKEN is not set. Set it via environment variable.", file=sys.stderr)

# Optional secret token for webhook verification (Telegram supports sending header X-Telegram-Bot-Api-Secret-Token)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()  # если вы хотите использовать секретный token
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()  # optional, can be set programmatically

# DB
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()  # e.g. postgresql://user:pass@host:5432/dbname

# Storage
MEDIA_DIR = os.getenv("MEDIA_DIR", "./media")  # filesystem storage
LOG_DIR = os.getenv("LOG_DIR", "./logs")

# Other
LISTEN_HOST = os.getenv("LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8000"))

# Ensure directories
os.makedirs(MEDIA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ---------------------------
# Logging configuration
# ---------------------------
logger = logging.getLogger("telegram_bot_single")
logger.setLevel(logging.INFO)
log_file_path = os.path.join(LOG_DIR, "bot.log")
# Ротация: новое каждый день, держать ~31 файл (месяц)
handler = TimedRotatingFileHandler(log_file_path, when="midnight", backupCount=31, encoding="utf-8")
handler.suffix = "%Y-%m-%d"
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
handler.setFormatter(formatter)
if not logger.handlers:
    logger.addHandler(handler)

# simple console handler for convenience
console_h = logging.StreamHandler()
console_h.setFormatter(formatter)
logger.addHandler(console_h)

# ---------------------------
# In-memory cache for media
# ---------------------------
# Structure: media_cache[file_id] = {"bytes": b'...', "user_id": 123, "type": "photo", "filename": "...", "ts": datetime}
media_cache: Dict[str, Dict[str, Any]] = {}

# ---------------------------
# FastAPI app
# ---------------------------
app = FastAPI(title="Telegram Bot Single File Library (FastAPI webhook)")

# ---------------------------
# Utility helpers for Telegram API
# ---------------------------
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
TELEGRAM_FILE_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}"


def _api_post(method: str, data: Optional[dict] = None, files: Optional[dict] = None, timeout: int = 30) -> dict:
    """Make POST request to Telegram API method and return parsed JSON or raise."""
    url = f"{TELEGRAM_API_BASE}/{method}"
    logger.debug("Request to Telegram API %s with data keys=%s files=%s", method, list((data or {}).keys()), list((files or {}).keys()))
    try:
        resp = requests.post(url, data=data, files=files, timeout=timeout)
        resp.raise_for_status()
        j = resp.json()
        if not j.get("ok"):
            logger.error("Telegram API responded not ok: %s", j)
            raise Exception(f"Telegram API error: {j}")
        return j
    except Exception as e:
        logger.exception("Error calling Telegram API %s: %s", method, e)
        raise


def set_webhook(url: str, secret_token: Optional[str] = None) -> dict:
    """
    Установить webhook для бота.
    url: полный URL (https) куда Telegram будет слать POST'ы
    secret_token: optional, будет передан в getUpdates и как заголовок X-Telegram-Bot-Api-Secret-Token
    """
    payload = {"url": url}
    if secret_token:
        payload["secret_token"] = secret_token
    logger.info("Setting webhook to %s (secret set: %s)", url, bool(secret_token))
    return _api_post("setWebhook", data=payload)


def delete_webhook() -> dict:
    """Удалить webhook (переключиться на getUpdates)."""
    logger.info("Deleting webhook")
    return _api_post("deleteWebhook")


def send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None, parse_mode: Optional[str] = None) -> dict:
    """
    Отправить текстовое сообщение в chat_id.
    reply_markup: dict, пример inline-клавиатуры:
      {
        "inline_keyboard": [
            [{"text": "Btn1", "callback_data": "action1"}],
            [{"text": "Btn2", "url": "https://example.com"}]
        ]
      }
    """
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    if parse_mode:
        payload["parse_mode"] = parse_mode
    logger.info("send_message chat=%s text=%s", chat_id, text[:50])
    return _api_post("sendMessage", data=payload)


def send_photo(chat_id: int, photo_path: Optional[str] = None, photo_bytes: Optional[bytes] = None,
               caption: Optional[str] = None) -> dict:
    """
    Отправить фото: можно передать путь к файлу или байты.
    Если оба указаны - приоритет у photo_bytes.
    """
    if photo_bytes is not None:
        files = {"photo": ("photo.jpg", io.BytesIO(photo_bytes))}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        logger.info("send_photo chat=%s bytes_size=%s", chat_id, len(photo_bytes))
        return _api_post("sendPhoto", data=data, files=files)
    elif photo_path:
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            logger.info("send_photo chat=%s file=%s", chat_id, photo_path)
            return _api_post("sendPhoto", data=data, files=files)
    else:
        raise ValueError("Either photo_path or photo_bytes must be provided")


def send_video(chat_id: int, video_path: Optional[str] = None, video_bytes: Optional[bytes] = None,
               caption: Optional[str] = None) -> dict:
    """
    Отправить видео аналогично send_photo.
    """
    if video_bytes is not None:
        files = {"video": ("video.mp4", io.BytesIO(video_bytes))}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
        logger.info("send_video chat=%s bytes_size=%s", chat_id, len(video_bytes))
        return _api_post("sendVideo", data=data, files=files)
    elif video_path:
        with open(video_path, "rb") as f:
            files = {"video": f}
            data = {"chat_id": chat_id}
            if caption:
                data["caption"] = caption
            logger.info("send_video chat=%s file=%s", chat_id, video_path)
            return _api_post("sendVideo", data=data, files=files)
    else:
        raise ValueError("Either video_path or video_bytes must be provided")


def get_file_path(file_id: str) -> str:
    """
    Получить file_path по file_id через метод getFile.
    Возвращает относительный путь (например, photos/file_123.jpg).
    """
    logger.debug("get_file_path for %s", file_id)
    resp = _api_post("getFile", data={"file_id": file_id})
    result = resp.get("result", {})
    file_path = result.get("file_path")
    if not file_path:
        raise Exception(f"getFile did not return file_path for {file_id}: {resp}")
    return file_path


def download_file_by_path(file_path: str) -> bytes:
    """
    Скачать файл по file_path, вернув bytes.
    URL: https://api.telegram.org/file/bot<token>/<file_path>
    """
    url = f"{TELEGRAM_FILE_BASE}/{file_path}"
    logger.debug("Downloading file from %s", url)
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    return r.content


# ---------------------------
# Media saving helpers
# ---------------------------

def save_media_to_fs(file_bytes: bytes, filename: str) -> str:
    """
    Сохранить байты в MEDIA_DIR и вернуть путь.
    Принимает filename (может быть только имя, без пути).
    """
    safe_name = filename.replace("/", "_").replace("\\", "_")
    dest = os.path.join(MEDIA_DIR, f"{int(time.time())}_{safe_name}")
    with open(dest, "wb") as f:
        f.write(file_bytes)
    logger.info("Saved media to filesystem: %s (size=%d)", dest, len(file_bytes))
    return dest


def save_media_to_db(file_bytes: bytes, user_id: int, file_id: str, media_type: str, file_name: Optional[str] = None) -> bool:
    """
    Сохранить медиа в PostgreSQL в таблицу media.
    Требует DATABASE_URL и установленного psycopg2.
    Возвращает True при успехе, False при ошибке.

    Примечание: таблица media должна быть создана заранее.
    SQL-пример:
        CREATE TABLE IF NOT EXISTS media (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            file_id TEXT,
            media_type TEXT,
            file_name TEXT,
            data BYTEA,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set, skipping DB save")
        return False
    if psycopg2 is None:
        logger.warning("psycopg2 not installed, skipping DB save")
        return False

    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO media (user_id, file_id, media_type, file_name, data) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, file_id, media_type, file_name, psycopg2.Binary(file_bytes))
                )
            conn.commit()
        logger.info("Saved media to DB user=%s file_id=%s type=%s", user_id, file_id, media_type)
        return True
    except Exception as e:
        logger.exception("Failed to save media to DB: %s", e)
        return False


# ---------------------------
# User existence check (заглушка)
# ---------------------------

def user_exists(user_id: int) -> bool:
    """
    Заглушка проверки наличия пользователя в системе.
    Замените тело на запрос в базу данных.

    Пример реализации через psycopg2:
        def user_exists(user_id):
            if not DATABASE_URL:
                return False
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
                    return cur.fetchone() is not None

    Пока возвращает True (разрешаем всем).
    """
    # TODO: Реализовать реальную проверку через PostgreSQL здесь.
    logger.debug("user_exists placeholder called for user=%s", user_id)
    return True


# ---------------------------
# Update processing
# ---------------------------

def process_update(update: dict):
    """
    Обработчик входящего update (выполняется при получении webhook'а).
    Сохраняет фото и видео в память, на диск и в БД (в зависимости от настроек).
    """
    logger.info("Processing update keys=%s", list(update.keys()))
    try:
        # basic message handling
        message = update.get("message") or update.get("edited_message")
        if message is None:
            # handle callback_query etc.
            if "callback_query" in update:
                cb = update["callback_query"]
                logger.info("Received callback_query from user %s data=%s", cb.get("from", {}).get("id"), cb.get("data"))
                # Respond to callback if desired (answerCallbackQuery)
                # _api_post("answerCallbackQuery", data={"callback_query_id": cb["id"]})
            return

        user = message.get("from", {})
        user_id = user.get("id")
        chat = message.get("chat", {})
        chat_id = chat.get("id")

        # Example security: check user exists
        if not user_exists(user_id):
            logger.warning("User %s not found in DB (placeholder). Ignoring message.", user_id)
            # optionally send a message telling user to register
            try:
                send_message(chat_id, "Вы не зарегистрированы в сервисе. Пожалуйста, зарегистрируйтесь.")
            except Exception:
                pass
            return

        # Save photos
        if "photo" in message:
            # 'photo' is an array of PhotoSize — choose the largest (last)
            photos = message["photo"]
            if isinstance(photos, list) and photos:
                largest = photos[-1]
                file_id = largest.get("file_id")
                logger.info("Incoming photo file_id=%s from user=%s", file_id, user_id)
                try:
                    file_path = get_file_path(file_id)
                    file_bytes = download_file_by_path(file_path)
                    # Save to memory
                    media_cache[file_id] = {
                        "bytes": file_bytes,
                        "user_id": user_id,
                        "type": "photo",
                        "filename": os.path.basename(file_path),
                        "ts": datetime.datetime.utcnow().isoformat()
                    }
                    # Save to filesystem
                    fs_path = save_media_to_fs(file_bytes, os.path.basename(file_path))
                    # Save to DB
                    save_media_to_db(file_bytes, user_id, file_id, "photo", os.path.basename(file_path))
                    # Optionally notify user
                    send_message(chat_id, f"Фото получено и сохранено (файл: {os.path.basename(fs_path)})")
                except Exception as e:
                    logger.exception("Error processing photo: %s", e)
                    send_message(chat_id, "Ошибка при обработке фото.")
        # Save video
        if "video" in message:
            video = message["video"]
            file_id = video.get("file_id")
            logger.info("Incoming video file_id=%s from user=%s", file_id, user_id)
            try:
                file_path = get_file_path(file_id)
                file_bytes = download_file_by_path(file_path)
                # Save to memory
                media_cache[file_id] = {
                    "bytes": file_bytes,
                    "user_id": user_id,
                    "type": "video",
                    "filename": os.path.basename(file_path),
                    "ts": datetime.datetime.utcnow().isoformat()
                }
                fs_path = save_media_to_fs(file_bytes, os.path.basename(file_path))
                save_media_to_db(file_bytes, user_id, file_id, "video", os.path.basename(file_path))
                send_message(chat_id, f"Видео получено и сохранено (файл: {os.path.basename(fs_path)})")
            except Exception as e:
                logger.exception("Error processing video: %s", e)
                send_message(chat_id, "Ошибка при обработке видео.")
        # Text: respond to some command examples
        if "text" in message:
            text = message["text"].strip()
            logger.info("Text message from %s: %s", user_id, text[:80])
            # simple /start handler
            if text.startswith("/start"):
                kb = {
                    "inline_keyboard": [
                        [{"text": "Помощь", "callback_data": "help"}],
                        [{"text": "Посмотреть медиа (cache)", "callback_data": "list_cache"}]
                    ]
                }
                send_message(chat_id, "Привет! Я готов принимать медиа. Отправь фото или видео.", reply_markup=kb)
            # custom command to list cached media ids
            elif text.startswith("/list_cache"):
                keys = list(media_cache.keys())
                send_message(chat_id, f"Cached file_ids ({len(keys)}):\n" + ("\n".join(keys) if keys else "нет"))
            # echo otherwise
            else:
                send_message(chat_id, f"Вы написали: {text}")
    except Exception as e:
        logger.exception("Unhandled exception in process_update: %s", e)


# ---------------------------
# Webhook endpoint
# ---------------------------

@app.post("/webhook/{secret_path:path}")
async def webhook_endpoint(request: Request, secret_path: str, x_telegram_bot_api_secret_token: Optional[str] = Header(None)):
    """
    Основной endpoint для webhook: POST /webhook/{secret}
    Если вы используете TELEGRAM webhook secret, Telegram отправит заголовок:
      X-Telegram-Bot-Api-Secret-Token: <secret>
    Здесь мы проверяем совпадение с WEBHOOK_SECRET (если установлен).
    """
    # Check secret path optionally
    if WEBHOOK_SECRET:
        # If both secret path and header are set, prefer header check (telegram supports secret_token -> header)
        header_token = x_telegram_bot_api_secret_token
        if header_token:
            if header_token != WEBHOOK_SECRET:
                logger.warning("Webhook secret header mismatch. Provided=%s", header_token)
                raise HTTPException(status_code=403, detail="Invalid webhook secret header")
        else:
            # fall back to path check
            if secret_path != WEBHOOK_SECRET and WEBHOOK_SECRET != "":
                logger.warning("Webhook secret path mismatch. path=%s expected=%s", secret_path, WEBHOOK_SECRET)
                raise HTTPException(status_code=403, detail="Invalid webhook path secret")
    # Parse JSON body
    try:
        payload = await request.json()
    except Exception as e:
        logger.exception("Failed to parse webhook JSON: %s", e)
        raise HTTPException(status_code=400, detail="invalid json")
    # Process update in background so Telegram gets fast 200
    try:
        asyncio.create_task(asyncio.to_thread(process_update, payload))
    except Exception:
        # last resort synchronous
        process_update(payload)
    return JSONResponse(status_code=200, content={"ok": True})


# ---------------------------
# Background tasks: monthly log cleanup
# ---------------------------
def _remove_old_logs(older_than_days: int = 35):
    """
    Удаляем лог-файлы в LOG_DIR старше older_than_days.
    Запускается фоново в начале каждого нового месяца.
    """
    now = time.time()
    cutoff = now - older_than_days * 24 * 3600
    removed = []
    for fname in os.listdir(LOG_DIR):
        if not fname.endswith(".log") and not fname.startswith("bot.log"):
            continue
        path = os.path.join(LOG_DIR, fname)
        try:
            mtime = os.path.getmtime(path)
            if mtime < cutoff:
                os.remove(path)
                removed.append(path)
        except Exception as e:
            logger.exception("Error while removing log file %s: %s", path, e)
    if removed:
        logger.info("Removed %d old log files: %s", len(removed), removed)
    else:
        logger.info("No old log files to remove")


async def monthly_cleanup_loop():
    """
    Фоновая корутина: ждет до следующего первого числа месяца 00:05 и запускает очистку.
    После выполнения — ждёт следующий месяц и т.д.
    """
    logger.info("Starting monthly cleanup loop")
    while True:
        now = datetime.datetime.now()
        # compute next month's first day at 00:05
        year = now.year + (1 if now.month == 12 else 0)
        month = 1 if now.month == 12 else now.month + 1
        next_run = datetime.datetime(year=year, month=month, day=1, hour=0, minute=5, second=0)
        sleep_seconds = (next_run - now).total_seconds()
        logger.info("Monthly cleanup sleeping for %s seconds until %s", int(sleep_seconds), next_run.isoformat())
        try:
            await asyncio.sleep(sleep_seconds)
        except asyncio.CancelledError:
            logger.info("Monthly cleanup loop cancelled")
            return
        try:
            _remove_old_logs(older_than_days=31)
        except Exception as e:
            logger.exception("Error during monthly cleanup: %s", e)
        # loop to compute next iteration


@app.on_event("startup")
async def startup_event():
    logger.info("App startup")
    # launch monthly cleanup background task
    try:
        asyncio.create_task(monthly_cleanup_loop())
    except Exception as e:
        logger.exception("Failed to start monthly cleanup background task: %s", e)

    # Optionally set webhook automatically if WEBHOOK_URL env var is set:
    if WEBHOOK_URL:
        try:
            set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET or None)
        except Exception as e:
            logger.exception("Failed to set webhook on startup: %s", e)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("App shutdown")


# ---------------------------
# Small admin endpoints (optional)
# ---------------------------

@app.get("/healthz")
def healthz():
    return {"ok": True, "time": datetime.datetime.utcnow().isoformat()}


@app.get("/cache_keys")
def cache_keys():
    """Вернуть список ключей кэша (file_id -> meta)."""
    return {"count": len(media_cache), "keys": list(media_cache.keys())}


@app.post("/admin/delete_cache/{file_id}")
def admin_delete_cache(file_id: str):
    """Удалить объект из кэша (для отладки)."""
    if file_id in media_cache:
        del media_cache[file_id]
        return {"deleted": file_id}
    return {"deleted": None, "msg": "not found"}


# ---------------------------
# If run as script — стартуем uvicorn
# ---------------------------
if __name__ == "__main__":
    # when launched directly, run uvicorn server
    import uvicorn
    logger.info("Starting uvicorn on %s:%d", LISTEN_HOST, LISTEN_PORT)
    uvicorn.run("telegram_bot_single:app", host=LISTEN_HOST, port=LISTEN_PORT, log_level="info")

