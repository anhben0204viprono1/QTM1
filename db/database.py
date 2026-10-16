"""Hàm dùng chung cho cả collector (A) và API Flask (B)."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("NETMON_DB", _HERE / "netmon.db"))
SCHEMA_PATH = _HERE / "schema.sql"

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc() -> str:
    """Timestamp chuẩn của dự án: ISO8601 UTC, không có microsecond, kết thúc bằng Z."""
    return datetime.now(timezone.utc).strftime(TS_FORMAT)


def parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, TS_FORMAT).replace(tzinfo=timezone.utc)


def connect(db_path=None) -> sqlite3.Connection:
    """Mở kết nối. PHẢI dùng hàm này ở mọi nơi để PRAGMA được bật cho từng kết nối."""
    con = sqlite3.connect(db_path or DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def init_db(db_path=None) -> None:
    """Tạo bảng nếu chưa có và bật WAL (collector ghi, Flask đọc cùng lúc)."""
    con = connect(db_path)
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    con.commit()
    con.close()
