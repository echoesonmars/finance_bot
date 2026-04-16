"""Load configuration from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root (directory containing this file)
ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

# SQLite database file path
DATABASE_PATH = str(ROOT_DIR / "finance_bot.db")

# Default reporting period for charts and GPT context (days)
DEFAULT_STATS_DAYS = 7
