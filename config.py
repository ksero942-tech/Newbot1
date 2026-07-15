import os

# Токен твоего Telegram-бота (берется из переменной BOT_TOKEN в Railway)
TOKEN = os.getenv("BOT_TOKEN")

# Ссылка на базу данных PostgreSQL (берется из переменной DATABASE_URL в Railway)
DATABASE_URL = os.getenv("DATABASE_URL")

# Автоматическое исправление ссылки для SQLAlchemy 2.x:
# Railway по умолчанию выдает ссылку, начинающуюся с "postgres://",
# но новая версия SQLAlchemy требует только "postgresql://" (с добавлением 'ql').
# Этот код сам исправит префикс, если это необходимо.
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
