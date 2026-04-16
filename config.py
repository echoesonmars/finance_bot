"""Загрузка настроек из переменных окружения и файла .env."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root (directory containing this file)
ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# Путь к файлу базы данных приложения
DATABASE_PATH = str(ROOT_DIR / "finance_bot.db")

# Сколько дней учитывать в графиках и в сводке для «Советы по тратам»
DEFAULT_STATS_DAYS = 7
