"""Keep backend tests off any real database.

Imported first by every test module. Blank Supabase settings win over backend/.env
(load_dotenv never overrides existing variables), so any database call a test does not
fake fails fast instead of reaching a real project. CI has no .env, so this matches CI.
"""

import os

os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_SECRET_KEY"] = ""

from app.data_store import get_supabase_client  # noqa: E402

get_supabase_client.cache_clear()
