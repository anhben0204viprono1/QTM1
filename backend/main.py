import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "monitor.db")))

app = FastAPI(title="Network Monitoring API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_connection():
    if not DB_PATH.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Không tìm thấy SQLite Database: {DB_PATH}. "
                   "Hãy đặt file .db vào backend/data/monitor.db hoặc cấu hình DATABASE_PATH."
        )
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def rows_to_dicts(rows):
    return [dict(row) for row in rows]

@app.get("/")
def root():
    return {
        "message": "Network Monitoring API đang chạy",
        "docs": "/docs",
        "database_path": str(DB_PATH),
    }

@app.get("/api/health")
def health():
    """Kiểm tra API, file SQLite và các bảng cốt lõi."""
    conn = get_connection()
    try:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
        required = {"devices", "metrics", "interfaces", "interface_stats", "alerts"}
        missing = sorted(required - tables)
        counts = {}
        for table in sorted(required & tables):
            # Table names come only from the fixed allowlist above.
            counts[table] = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
        return {
            "status": "ok" if not missing else "warning",
            "database_path": str(DB_PATH),
            "database_exists": True,
            "missing_tables": missing,
            "counts": counts,
        }
    finally:
        conn.close()

@app.get("/api/devices")
def get_devices():
    conn = get_connection()
    try:
        sql = """
        SELECT d.id, d.hostname, d.ip, d.vendor, d.device_type, d.status,
               d.last_seen, d.created_at,
               lm.timestamp AS metrics_timestamp,
               lm.cpu_percent, lm.ram_percent, lm.ram_used_mb, lm.ram_total_mb
        FROM devices d
        LEFT JOIN v_latest_metrics lm ON lm.device_id = d.id
        ORDER BY d.hostname
        """
        return rows_to_dicts(conn.execute(sql).fetchall())
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn devices/View: {exc}")
    finally:
        conn.close()

@app.get("/api/metrics")
def get_metrics(
    device_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=2000),
):
    conn = get_connection()
    try:
        if device_id is None:
            sql = """
                SELECT m.id, m.device_id, d.hostname, m.timestamp,
                       m.cpu_percent, m.ram_percent, m.ram_used_mb, m.ram_total_mb
                FROM metrics m JOIN devices d ON d.id = m.device_id
                ORDER BY m.timestamp DESC LIMIT ?
            """
            params = (limit,)
        else:
            sql = """
                SELECT m.id, m.device_id, d.hostname, m.timestamp,
                       m.cpu_percent, m.ram_percent, m.ram_used_mb, m.ram_total_mb
                FROM metrics m JOIN devices d ON d.id = m.device_id
                WHERE m.device_id = ?
                ORDER BY m.timestamp DESC LIMIT ?
            """
            params = (device_id, limit)
        # Return oldest-to-newest for charts.
        data = rows_to_dicts(conn.execute(sql, params).fetchall())
        data.reverse()
        return data
    finally:
        conn.close()

@app.get("/api/interfaces")
def get_interfaces(device_id: Optional[int] = Query(default=None, ge=1)):
    conn = get_connection()
    try:
        sql = """
        SELECT li.interface_id AS id, li.device_id, d.hostname, d.ip,
               li.name, li.description, li.speed_mbps, li.timestamp,
               li.status, li.in_bps, li.out_bps, li.in_errors, li.in_crc,
               li.out_errors, li.out_drops
        FROM v_latest_interfaces li
        JOIN devices d ON d.id = li.device_id
        """
        params = ()
        if device_id is not None:
            sql += " WHERE li.device_id = ?"
            params = (device_id,)
        sql += " ORDER BY d.hostname, li.name"
        return rows_to_dicts(conn.execute(sql, params).fetchall())
    except sqlite3.OperationalError as exc:
        raise HTTPException(status_code=500, detail=f"Lỗi truy vấn interfaces/View: {exc}")
    finally:
        conn.close()

@app.get("/api/alerts")
def get_alerts(
    resolved: Optional[int] = Query(default=None, ge=0, le=1),
    limit: int = Query(default=100, ge=1, le=1000),
):
    conn = get_connection()
    try:
        sql = """
        SELECT a.id, a.device_id, d.hostname, d.ip,
               a.interface_id, i.name AS interface_name,
               a.timestamp, a.type, a.severity, a.message,
               a.value, a.threshold, a.resolved, a.resolved_at
        FROM alerts a
        JOIN devices d ON d.id = a.device_id
        LEFT JOIN interfaces i ON i.id = a.interface_id
        """
        params = []
        if resolved is not None:
            sql += " WHERE a.resolved = ?"
            params.append(resolved)
        sql += " ORDER BY a.timestamp DESC LIMIT ?"
        params.append(limit)
        return rows_to_dicts(conn.execute(sql, params).fetchall())
    finally:
        conn.close()
