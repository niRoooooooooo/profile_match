
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]

load_dotenv(ROOT_DIR / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY")

QWEN_MODEL = os.getenv("QWEN_MODEL", "qwen3.5:9b")
QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL",
    "http://localhost:11434"
)

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError(
        "Missing Supabase configuration in .env"
    )
