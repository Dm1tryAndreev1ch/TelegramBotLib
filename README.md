webhook server for Telegram Bot API.

Содержит:
- FastAPI webhook endpoint для приёма обновлений от Telegram
- Функции для отправки сообщений, inline-клавиатур, фото и видео (через HTTP, без сторонних Telegram-обёрток)
- Скачивание медиа от пользователя (getFile -> download), сохранение в:
    * Оперативную память (cache)
    * Файловую систему (папка MEDIA_DIR)
    * PostgreSQL (таблица media)
- Заглушка `user_exists(user_id)` с комментариями, как реализовать через PostgreSQL (psycopg2)
- Логирование действий и фоновая очистка старых логов в конце месяца
- Докстринги и README-подсказки внизу модуля

Usage:
    export TELEGRAM_BOT_TOKEN="your_token"
    export WEBHOOK_URL="https://yourdomain.com/webhook/<secret>"  # или используйте set_webhook()
    export DATABASE_URL="postgresql://user:pass@host:5432/dbname"
    python3 telegram_bot_single.py  # запустит uvicorn

Dependencies (pip):
    fastapi uvicorn requests psycopg2-binary python-multipart

DB schema (пример):
    CREATE TABLE IF NOT EXISTS media (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        file_id TEXT,
        media_type TEXT,
        file_name TEXT,
        data BYTEA,
        created_at TIMESTAMP DEFAULT NOW()
    );

Примечания:
- Telegram позволяет установить секретный токен для webhook: мы поддерживаем проверку заголовка
  'X-Telegram-Bot-Api-Secret-Token' если вы укажете SECRET_TOKEN при setWebhook.
- Библиотека ориентирована на личное использование и простоту адаптации.

Краткая документация по функциям
# Краткая документация по функциям — `telegram_bot_single.py`

Ниже — компактные подсказки по основным функциям и эндпойнтам файла. Формат: что делает → параметры → что возвращает → короткий пример использования / примечание.

---

### `set_webhook(url: str, secret_token: Optional[str] = None) -> dict`

* Что делает: устанавливает webhook у Telegram (метод `setWebhook`).
* Параметры:

  * `url` — публичный HTTPS URL, на который Telegram будет слать обновления (например `https://example.com/webhook/mysecret`).
  * `secret_token` — опционально: Telegram пришлёт этот токен в заголовке `X-Telegram-Bot-Api-Secret-Token`.
* Возвращает: JSON-ответ Telegram (как `dict`) при успехе; исключение при ошибке.
* Пример:

```py
set_webhook("https://example.com/webhook/mysecret", secret_token="mysecret")
```

---

### `delete_webhook() -> dict`

* Что делает: удаляет webhook (переключает бота на `getUpdates` режим).
* Возвращает: JSON-ответ Telegram.
* Примечание: удобно для отладки.

---

### `send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None, parse_mode: Optional[str] = None) -> dict`

* Что делает: отправляет текстовое сообщение.
* Параметры:

  * `chat_id` — ID чата или пользователя.
  * `text` — текст сообщения.
  * `reply_markup` — опционально: словарь с inline-клавиатурой (будет сериализован в JSON).
  * `parse_mode` — опционально: `"HTML"` или `"MarkdownV2"`.
* Возвращает: JSON-ответ Telegram (инфо об отправленном сообщении).
* Пример:

```py
kb = {"inline_keyboard": [[{"text":"Ok","callback_data":"ok"}]]}
send_message(123456789, "Привет!", reply_markup=kb)
```

---

### `send_photo(chat_id: int, photo_path: Optional[str]=None, photo_bytes: Optional[bytes]=None, caption: Optional[str]=None) -> dict`

* Что делает: отправляет фото (файл с диска или байты).
* Параметры:

  * `photo_path` — путь к файлу (если указан `photo_bytes` — приоритет у байтов).
  * `photo_bytes` — байты изображения.
  * `caption` — подпись.
* Возвращает: JSON-ответ Telegram.
* Пример:

```py
with open("img.jpg","rb") as f: send_photo(123, photo_bytes=f.read(), caption="Фото")
```

---

### `send_video(chat_id: int, video_path: Optional[str]=None, video_bytes: Optional[bytes]=None, caption: Optional[str]=None) -> dict`

* Что делает: отправляет видео (аналогично `send_photo`).
* Параметры и поведение аналогичны `send_photo`.
* Пример:

```py
send_video(123, video_path="/tmp/clip.mp4", caption="Короткое видео")
```

---

### `get_file_path(file_id: str) -> str`

* Что делает: вызывает `getFile` у Telegram и возвращает `file_path` (строку).
* Параметры:

  * `file_id` — id файла из incoming message.
* Возвращает: `file_path` (например `"photos/file_123.jpg"`). Бросает исключение при ошибке.
* Пример:

```py
path = get_file_path("AgAC...")  # -> "photos/file_123.jpg"
```

---

### `download_file_by_path(file_path: str) -> bytes`

* Что делает: скачивает файл по `file_path` из Telegram (`https://api.telegram.org/file/bot<TOKEN>/<file_path>`).
* Параметры:

  * `file_path` — значение, полученное из `get_file_path`.
* Возвращает: байты файла (`bytes`).
* Пример:

```py
data = download_file_by_path("photos/file_123.jpg")
```

---

### `save_media_to_fs(file_bytes: bytes, filename: str) -> str`

* Что делает: сохраняет байты в папку `MEDIA_DIR` с префиксом времени; возвращает путь на диске.
* Параметры:

  * `file_bytes` — содержимое файла.
  * `filename` — имя файла (используется для формирования имени).
* Возвращает: путь к сохранённому файлу.
* Пример:

```py
path = save_media_to_fs(data, "file_123.jpg")
```

---

### `save_media_to_db(file_bytes: bytes, user_id: int, file_id: str, media_type: str, file_name: Optional[str] = None) -> bool`

* Что делает: сохраняет медиа в PostgreSQL (таблица `media`) как `BYTEA`.
* Параметры:

  * `file_bytes`, `user_id`, `file_id`, `media_type` (`"photo"`/`"video"`), `file_name`.
* Возвращает: `True` при успехе, `False` при ошибке или если `DATABASE_URL` не задан / `psycopg2` не установлен.
* Примечание: таблицу `media` нужно создать заранее (см. SQL в шапке файла).

---

### `user_exists(user_id: int) -> bool`

* Что делает: заглушка проверки пользователя.
* Поведение по-умолчанию: возвращает `True`.
* Как доработать: заменить реализацией через PostgreSQL (пример в коде и в документации).
* Используется `process_update` перед выполнением действий с пользователем.

---

### `process_update(update: dict) -> None`

* Что делает: основной процессинг входящего `Update` от Telegram:

  * Обрабатывает `message` (photo, video, text), сохраняет медиа в память/FS/DB и отвечает пользователю.
  * Обрабатывает (частично) `callback_query`.
* Параметры:

  * `update` — десериализованный JSON (словарь) из webhook.
* Возвращает: ничего; логирует и посылает ответы через `send_message`.
* Примечания:

  * Вызывается асинхронно из эндпойнта webhook (через `asyncio.to_thread`).
  * При ошибках логирует исключения.

---

### Webhook endpoint — `POST /webhook/{secret_path}`

* Что делает: принимает `Update` от Telegram.
* Безопасность:

  * Если установлен `WEBHOOK_SECRET`, проверяет заголовок `X-Telegram-Bot-Api-Secret-Token` (предпочтительно) или `secret_path`.
* Поведение:

  * Парсит JSON и запускает `process_update(update)` в фоне, возвращая `200` быстро.
* Пример curl:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"update_id":1, "message":{"message_id":1,"from":{"id":111},"chat":{"id":111},"text":"/start"}}' \
  https://yourdomain/webhook/mysecret
```

---

### Админ-эндпойнты

* `GET /healthz` — возвращает `{"ok": True, "time": ...}`.
* `GET /cache_keys` — возвращает ключи (file_id) и количество в in-memory `media_cache`.
* `POST /admin/delete_cache/{file_id}` — удаляет файл из `media_cache`.

> Примечание: эти эндпойнты **не защищены** по умолчанию — в проде добавьте защиту (IP whitelist / HTTP auth).

---

### Фоновые события

* `startup_event` — запускает background task `monthly_cleanup_loop()` и автоматически вызывает `set_webhook` если задан `WEBHOOK_URL`.
* `monthly_cleanup_loop()` — вычисляет следующее первое число месяца 00:05 и вызывает `_remove_old_logs(older_than_days=31)` (удаляет старые лог-файлы).

---
