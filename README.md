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
