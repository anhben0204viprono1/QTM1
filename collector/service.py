"""Thu thập 1 thiết bị (chạy trong thread) và lưu kết quả vào DB (chạy ở thread chính)."""
import logging
import time
from datetime import datetime, timedelta, timezone

from alerts import engine
from collector.errors import CollectError, ParseError
from collector.mock import fetch_raw_mock
from collector.netmiko_client import fetch_raw
from collector.parsers import parse_cpu, parse_interfaces, parse_memory
from db.database import TS_FORMAT, now_utc, parse_ts

log = logging.getLogger("collector")

MAX_GAP_SECONDS = 600  # hai mẫu cách nhau quá 10 phút thì không tính bps (collector đã dừng)


# ---------------------------------------------------------------- thu thập (thread)

def collect_one(dev: dict, use_mock: bool = False) -> dict:
    """SSH + parse. Không đụng DB. Luôn trả về dict, không raise."""
    try:
        raw = fetch_raw_mock(dev) if use_mock else fetch_raw(dev)
        ts = now_utc()  # thời điểm đọc bộ đếm, dùng để tính bps
        data = {
            "cpu": parse_cpu(raw["cpu"]),
            "mem": parse_memory(raw["mem"]),
            "interfaces": parse_interfaces(raw["intf"]),
        }
        return {"ok": True, "ts": ts, "data": data}
    except CollectError as e:
        return {"ok": False, "kind": "unreachable", "ts": now_utc(), "error": str(e)}
    except ParseError as e:
        return {"ok": False, "kind": "parse", "ts": now_utc(), "error": f"Lỗi parse: {e}"}
    except Exception as e:  # lỗi bất ngờ trong thread không được làm sập cả chu kỳ
        return {"ok": False, "kind": "unreachable", "ts": now_utc(), "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- tính toán

def calc_rate_bps(prev_octets, cur_octets, seconds):
    """bit/giây = delta_byte * 8 / delta_giây. None nếu chưa đủ dữ liệu hoặc counter bị reset."""
    if prev_octets is None or cur_octets is None or not (0 < seconds <= MAX_GAP_SECONDS):
        return None
    delta = cur_octets - prev_octets
    if delta < 0:  # thiết bị reboot / clear counters
        return None
    return delta * 8 / seconds


def calc_error_delta(prev, itf):
    """Số lỗi + CRC + drops mới kể từ lần đo trước. None nếu chưa có mẫu trước hoặc bị reset."""
    if prev is None:
        return None
    cur = itf["in_errors"] + itf["in_crc"] + itf["out_errors"] + itf["out_drops"]
    old = (prev["in_errors"] or 0) + (prev["in_crc"] or 0) + (prev["out_errors"] or 0) + (prev["out_drops"] or 0)
    delta = cur - old
    return delta if delta >= 0 else None


# ---------------------------------------------------------------- lưu DB (thread chính)

def sync_devices(con, devices: list[dict]) -> None:
    """Đồng bộ danh sách thiết bị trong file cấu hình vào bảng devices."""
    for d in devices:
        con.execute(
            """INSERT INTO devices (hostname, ip, vendor, device_type)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(hostname) DO UPDATE SET
                   ip = excluded.ip, vendor = excluded.vendor, device_type = excluded.device_type""",
            (d["hostname"], d["ip"], d.get("vendor", "cisco"), d.get("device_type", "cisco_ios")),
        )
    con.commit()


def _get_interface_id(con, device_id, itf) -> int:
    con.execute(
        "INSERT OR IGNORE INTO interfaces (device_id, name, description, speed_mbps) VALUES (?, ?, ?, ?)",
        (device_id, itf["name"], itf["description"], itf["speed_mbps"]),
    )
    row = con.execute(
        "SELECT id FROM interfaces WHERE device_id = ? AND name = ?", (device_id, itf["name"])
    ).fetchone()
    con.execute(
        "UPDATE interfaces SET description = ?, speed_mbps = ? WHERE id = ?",
        (itf["description"], itf["speed_mbps"], row["id"]),
    )
    return row["id"]


def store_result(con, dev: dict, result: dict, th: dict) -> None:
    host = dev["hostname"]
    row = con.execute("SELECT id FROM devices WHERE hostname = ?", (host,)).fetchone()
    if row is None:
        raise RuntimeError(f"{host} chưa có trong bảng devices (gọi sync_devices trước)")
    device_id, ts = row["id"], result["ts"]

    # --- thất bại ---
    if not result["ok"]:
        log.error("[%s] %s", host, result["error"])
        if result["kind"] == "unreachable":
            con.execute("UPDATE devices SET status = 'down' WHERE id = ?", (device_id,))
            engine.device_unreachable(con, device_id, host, result["error"], ts)
        con.commit()
        return

    # --- thành công ---
    data = result["data"]
    con.execute("UPDATE devices SET status = 'up', last_seen = ? WHERE id = ?", (ts, device_id))
    engine.device_reachable(con, device_id, ts)

    cpu, mem = data["cpu"], data["mem"]
    con.execute(
        """INSERT OR IGNORE INTO metrics
           (device_id, timestamp, cpu_percent, ram_percent, ram_used_mb, ram_total_mb)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (device_id, ts, cpu["cpu_5s"], mem["ram_percent"], mem["ram_used_mb"], mem["ram_total_mb"]),
    )
    engine.check_cpu_ram(con, device_id, host, cpu["cpu_5s"], mem["ram_percent"], th, ts)

    watch = set(dev["watch_interfaces"]) if dev.get("watch_interfaces") else None
    for itf in data["interfaces"]:
        interface_id = _get_interface_id(con, device_id, itf)
        prev = con.execute(
            """SELECT timestamp, in_octets, out_octets, in_errors, in_crc, out_errors, out_drops
               FROM interface_stats WHERE interface_id = ? ORDER BY timestamp DESC LIMIT 1""",
            (interface_id,),
        ).fetchone()

        in_bps = out_bps = None
        if prev is not None:
            seconds = (parse_ts(ts) - parse_ts(prev["timestamp"])).total_seconds()
            in_bps = calc_rate_bps(prev["in_octets"], itf["in_octets"], seconds)
            out_bps = calc_rate_bps(prev["out_octets"], itf["out_octets"], seconds)
        err_delta = calc_error_delta(prev, itf)

        con.execute(
            """INSERT OR IGNORE INTO interface_stats
               (interface_id, timestamp, status, in_octets, out_octets, in_bps, out_bps,
                in_errors, in_crc, out_errors, out_drops)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (interface_id, ts, itf["status"], itf["in_octets"], itf["out_octets"], in_bps, out_bps,
             itf["in_errors"], itf["in_crc"], itf["out_errors"], itf["out_drops"]),
        )
        engine.check_interface(con, device_id, host, interface_id, itf["name"], itf["status"],
                               in_bps, out_bps, itf["speed_mbps"], err_delta, watch, th, ts)
    con.commit()


def cleanup_old(con, keep_hours: int = 48, keep_resolved_days: int = 7) -> None:
    """Xoá dữ liệu cũ để DB không phình to."""
    now = datetime.now(timezone.utc)
    cut = (now - timedelta(hours=keep_hours)).strftime(TS_FORMAT)
    cut_alert = (now - timedelta(days=keep_resolved_days)).strftime(TS_FORMAT)
    n1 = con.execute("DELETE FROM metrics WHERE timestamp < ?", (cut,)).rowcount
    n2 = con.execute("DELETE FROM interface_stats WHERE timestamp < ?", (cut,)).rowcount
    n3 = con.execute("DELETE FROM alerts WHERE resolved = 1 AND resolved_at < ?", (cut_alert,)).rowcount
    con.commit()
    log.info("Dọn dữ liệu cũ: metrics=%d, interface_stats=%d, alerts=%d", n1, n2, n3)
