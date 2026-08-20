import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jobradar_app.runtime_env import load_env_file

load_env_file(Path.home() / ".hermes" / "scripts" / "jobradar.env")
load_env_file(ROOT / ".env.jobradar")
os.environ.setdefault("JOBRADAR_TIMEZONE", os.environ.get("TZ", "America/Chicago"))
os.environ.setdefault("TZ", os.environ["JOBRADAR_TIMEZONE"])
if hasattr(time, "tzset"):
    time.tzset()

if os.environ.get("CAREEROPS_ROOT") and not os.environ.get("JOBRADAR_CAREEROPS_ROOT"):
    os.environ["JOBRADAR_CAREEROPS_ROOT"] = os.environ["CAREEROPS_ROOT"]
if os.environ.get("NODE_BIN") and not os.environ.get("JOBRADAR_NODE_BIN"):
    os.environ["JOBRADAR_NODE_BIN"] = os.environ["NODE_BIN"]

bind = os.environ.get("JOBRADAR_BIND_HOST", "127.0.0.1")
port = os.environ.get("JOBRADAR_BIND_PORT", "8765")
secret = os.environ.get("JOBRADAR_SECRET_KEY", "change-me-before-prod")
password_hash = os.environ.get(
    "JOBRADAR_PASSWORD_HASH",
    "$argon2id$v=19$m=65536,t=3,p=4$scRJ6U8GGR4dlf14QB1jEQ$E686+9u61jaYfDf25YfQAMnNrlipLdj0rEw0t9qIXPk",
)
session_dir = os.environ.get("JOBRADAR_SESSION_DIR", str(ROOT / "state" / "sessions"))

db_path = os.environ.get("JOBRADAR_DB_PATH", str(ROOT / "state" / "jobradar.sqlite3"))
import_dir = os.environ.get("JOBRADAR_IMPORT_DIR", str(ROOT / "processed"))

os.environ.setdefault("JOBRADAR_BIND_HOST", bind)
os.environ.setdefault("JOBRADAR_BIND_PORT", port)
os.environ.setdefault("JOBRADAR_SECRET_KEY", secret)
os.environ.setdefault("JOBRADAR_PASSWORD_HASH", password_hash)
os.environ.setdefault("JOBRADAR_SESSION_DIR", session_dir)
os.environ.setdefault("JOBRADAR_DB_PATH", db_path)
os.environ.setdefault("JOBRADAR_IMPORT_DIR", import_dir)

from web.server import main

if __name__ == "__main__":
    main()
