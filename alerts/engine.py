"""Alert engine: so sánh số liệu với ngưỡng, tạo / đóng cảnh báo trong bảng alerts.

Nhờ unique index uq_alerts_open, mỗi (thiết bị, interface, loại) chỉ có 1 cảnh báo đang mở,
nên collector có thể gọi các hàm check_* ở MỌI chu kỳ mà không sinh cảnh báo trùng.
"""
import logging

import yaml

log = logging.getLogger("alerts")


def load_thresholds(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------- tạo / đóng cảnh báo ----------

def raise_alert(con, device_id, interface_id, type_, severity, message, value, threshold, ts) -> bool:
    """Tạo cảnh báo mới. Nếu đã có cảnh báo mở cùng loại thì chỉ cập nhật mức độ/giá trị.
    Trả về True nếu là cảnh báo MỚI."""
    cur = con.execute(
        """INSERT OR IGNORE INTO alerts
           (device_id, interface_id, timestamp, type, severity, message, value, threshold)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (device_id, interface_id, ts, type_, severity, message, value, threshold),
    )
    if cur.rowcount == 1:
        log.warning("ALERT [%s] %s", severity.upper(), message)
        return True
    con.execute(
        """UPDATE alerts SET severity = ?, message = ?, value = ?, threshold = ?
           WHERE device_id = ? AND COALESCE(interface_id, 0) = COALESCE(?, 0)
             AND type = ? AND resolved = 0""",
        (severity, message, value, threshold, device_id, interface_id, type_),
    )
    return False


def resolve_alert(con, device_id, interface_id, type_, ts) -> bool:
    cur = con.execute(
        """UPDATE alerts SET resolved = 1, resolved_at = ?
           WHERE device_id = ? AND COALESCE(interface_id, 0) = COALESCE(?, 0)
             AND type = ? AND resolved = 0""",
        (ts, device_id, interface_id, type_),
    )
    if cur.rowcount:
        log.info("RESOLVED %s (device_id=%s, interface_id=%s)", type_, device_id, interface_id)
    return cur.rowcount > 0


def _check_level(con, device_id, interface_id, type_, text, value, levels, unit, ts):
    """Vượt ngưỡng critical -> critical, vượt warning -> warning, ngược lại đóng cảnh báo."""
    severity = threshold = None
    if "critical" in levels and value >= levels["critical"]:
        severity, threshold = "critical", levels["critical"]
    elif value >= levels["warning"]:
        severity, threshold = "warning", levels["warning"]

    if severity:
        msg = f"{text}: {value:.1f}{unit} (ngưỡng {severity}: {threshold}{unit})"
        raise_alert(con, device_id, interface_id, type_, severity, msg, value, threshold, ts)
    else:
        resolve_alert(con, device_id, interface_id, type_, ts)


# ---------- các luật ----------

def device_unreachable(con, device_id, host, error, ts):
    raise_alert(con, device_id, None, "device_unreachable", "critical",
                f"{host}: không thu thập được dữ liệu ({error})", None, None, ts)


def device_reachable(con, device_id, ts):
    resolve_alert(con, device_id, None, "device_unreachable", ts)


def check_cpu_ram(con, device_id, host, cpu, ram, th, ts):
    _check_level(con, device_id, None, "high_cpu", f"{host}: CPU", cpu, th["cpu_percent"], "%", ts)
    _check_level(con, device_id, None, "high_ram", f"{host}: RAM", ram, th["ram_percent"], "%", ts)


def check_interface(con, device_id, host, interface_id, name, status,
                    in_bps, out_bps, speed_mbps, err_delta, watch, th, ts):
    label = f"{host} {name}"

    # 1. interface_down: chỉ cảnh báo trạng thái 'down' (admin_down là do người quản trị tắt).
    #    Nếu thiết bị có khai báo watch_interfaces thì chỉ theo dõi các interface đó.
    watched = watch is None or name in watch
    if status == "down" and watched:
        raise_alert(con, device_id, interface_id, "interface_down", "critical",
                    f"{label}: interface DOWN", None, None, ts)
    else:
        resolve_alert(con, device_id, interface_id, "interface_down", ts)

    # 2. high_traffic: % băng thông = max(in, out) / tốc độ interface
    if speed_mbps and in_bps is not None and out_bps is not None:
        util = max(in_bps, out_bps) / (speed_mbps * 1_000_000) * 100
        _check_level(con, device_id, interface_id, "high_traffic",
                     f"{label}: traffic", util, th["traffic_percent"], "%", ts)

    # 3. high_errors: số lỗi/CRC/drops MỚI trong chu kỳ (delta)
    if err_delta is not None:
        limit = th["errors_delta"]["warning"]
        if err_delta >= limit:
            raise_alert(con, device_id, interface_id, "high_errors", "warning",
                        f"{label}: {err_delta} lỗi/CRC/drops mới trong 1 chu kỳ (ngưỡng {limit})",
                        err_delta, limit, ts)
        else:
            resolve_alert(con, device_id, interface_id, "high_errors", ts)
