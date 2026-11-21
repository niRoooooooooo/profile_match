
from functools import lru_cache
from supabase import create_client, Client

from app.config import SUPABASE_URL, SUPABASE_KEY


@lru_cache(maxsize=1)
def get_public_supabase() -> Client:
    return create_client(
        SUPABASE_URL,
        SUPABASE_KEY
    )
