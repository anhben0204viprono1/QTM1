#!/usr/bin/env python3
"""Sinh dữ liệu giả cho Dashboard giám sát mạng.

Chạy:
    python seed_data.py                 # tạo monitor.db từ schema.sql, thêm dữ liệu giả
    python seed_data.py --reset         # xoá DB cũ rồi tạo lại
    python seed_data.py --minutes 120 --step 30

Kịch bản có sẵn để test giao diện:
    R1  : CPU tăng vọt 10 phút gần nhất + Gi0/1 traffic > 80% băng thông
    R2  : Gi0/2 bị down
    SW1 : Fa0/2 tăng CRC/lỗi (cảnh báo đã resolved)
    SW2 : mất kết nối (status down, dữ liệu dừng cách đây 15 phút)
"""
import argparse
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
FMT = "%Y-%m-%dT%H:%M:%SZ"

DEVICES = [
    # hostname, ip, vendor, device_type, speed_mbps của interface
    ("R1", "192.168.1.1", "cisco", "cisco_ios", 1000),
    ("R2", "192.168.1.2", "cisco", "cisco_ios", 1000),
    ("SW1", "192.168.1.11", "cisco", "cisco_ios", 100),
    ("SW2", "192.168.1.12", "cisco", "cisco_ios", 100),
]
IFACES = {
    "R1": ["GigabitEthernet0/0", "GigabitEthernet0/1", "GigabitEthernet0/2"],
    "R2": ["GigabitEthernet0/0", "GigabitEthernet0/1", "GigabitEthernet0/2"],
    "SW1": ["FastEthernet0/1", "FastEthernet0/2", "FastEthernet0/3"],
    "SW2": ["FastEthernet0/1", "FastEthernet0/2", "FastEthernet0/3"],
}


def ts(dt):
    return dt.strftime(FMT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(HERE, "monitor.db"))
    ap.add_argument("--schema", default=os.path.join(HERE, "schema.sql"))
    ap.add_argument("--minutes", type=int, default=60, help="độ dài lịch sử")
    ap.add_argument("--step", type=int, default=30, help="chu kỳ thu thập (giây)")
    ap.add_argument("--reset", action="store_true", help="xoá DB cũ")
    args = ap.parse_args()

    random.seed(42)
    if args.reset and os.path.exists(args.db):
        os.remove(args.db)

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys = ON")
    with open(args.schema, encoding="utf-8") as f:
        con.executescript(f.read())
    if con.execute("SELECT COUNT(*) FROM devices").fetchone()[0]:
        raise SystemExit("DB đã có dữ liệu. Dùng --reset để tạo lại.")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    n = args.minutes * 60 // args.step
    times = [now - timedelta(seconds=args.step * (n - 1 - i)) for i in range(n)]
    dev_id, if_id = {}, {}

    # ---- devices + interfaces ----
    for host, ip, vendor, dtype, speed in DEVICES:
        status = "down" if host == "SW2" else "up"
        last_seen = ts(now - timedelta(minutes=15)) if host == "SW2" else ts(now)
        cur = con.execute(
            "INSERT INTO devices(hostname, ip, vendor, device_type, status, last_seen) "
            "VALUES (?,?,?,?,?,?)", (host, ip, vendor, dtype, status, last_seen))
        dev_id[host] = cur.lastrowid
        for name in IFACES[host]:
            cur = con.execute(
                "INSERT INTO interfaces(device_id, name, description, speed_mbps) "
                "VALUES (?,?,?,?)", (dev_id[host], name, f"Uplink {name}", speed))
            if_id[(host, name)] = cur.lastrowid

    # ---- metrics + interface_stats ----
    for host, _, _, _, speed in DEVICES:
        alive = [t for t in times
                 if not (host == "SW2" and t > now - timedelta(minutes=15))]
        base_cpu = random.uniform(15, 35)
        ram_total = 2048.0
        ram_base = random.uniform(45, 60)
        for i, t in enumerate(alive):
            cpu = base_cpu + 8 * math.sin(i / 6) + random.uniform(-3, 3)
            if host == "R1" and t > now - timedelta(minutes=10):
                cpu = random.uniform(88, 96)
            ram = min(99, ram_base + i * 0.02 + random.uniform(-1, 1))
            cpu = max(1, min(100, cpu))
            con.execute(
                "INSERT INTO metrics(device_id, timestamp, cpu_percent, ram_percent, "
                "ram_used_mb, ram_total_mb) VALUES (?,?,?,?,?,?)",
                (dev_id[host], ts(t), round(cpu, 1), round(ram, 1),
                 round(ram_total * ram / 100, 1), ram_total))

        for name in IFACES[host]:
            iid = if_id[(host, name)]
            in_oct = random.randint(10**9, 5 * 10**9)   # bộ đếm tích lũy (byte)
            out_oct = random.randint(10**9, 5 * 10**9)
            in_err = in_crc = out_err = out_drops = 0
            frac = random.uniform(0.05, 0.35)           # tỉ lệ băng thông dùng
            for t in alive:
                status = "up"
                f = max(0.01, frac + random.uniform(-0.05, 0.05))
                if host == "R1" and name.endswith("0/1") and t > now - timedelta(minutes=8):
                    f = random.uniform(0.82, 0.95)       # > 80% băng thông
                if host == "R2" and name.endswith("0/2") and t > now - timedelta(minutes=10):
                    status, f = "down", 0
                in_bps = speed * 1e6 * f
                out_bps = speed * 1e6 * max(0, f + random.uniform(-0.05, 0.05))
                in_oct += int(in_bps * args.step / 8)
                out_oct += int(out_bps * args.step / 8)
                if status == "up":
                    in_err += random.choice([0, 0, 0, 1])
                    out_drops += random.choice([0, 0, 0, 0, 1])
                    if host == "SW1" and name.endswith("0/2") and now - timedelta(minutes=40) < t < now - timedelta(minutes=30):
                        in_crc += random.randint(5, 20)
                        in_err += random.randint(5, 20)
                con.execute(
                    "INSERT INTO interface_stats(interface_id, timestamp, status, in_octets, "
                    "out_octets, in_bps, out_bps, in_errors, in_crc, out_errors, out_drops) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (iid, ts(t), status, in_oct, out_oct, round(in_bps, 1),
                     round(out_bps, 1), in_err, in_crc, out_err, out_drops))

    # ---- alerts ----
    def alert(host, iface, minutes_ago, typ, sev, msg, value, thr, resolved):
        con.execute(
            "INSERT INTO alerts(device_id, interface_id, timestamp, type, severity, message, "
            "value, threshold, resolved, resolved_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (dev_id[host], if_id.get((host, iface)) if iface else None,
             ts(now - timedelta(minutes=minutes_ago)), typ, sev, msg, value, thr,
             int(resolved),
             ts(now - timedelta(minutes=minutes_ago - 5)) if resolved else None))

    alert("R1", None, 9, "high_cpu", "critical", "CPU R1 đạt 93%", 93, 90, False)
    alert("R1", "GigabitEthernet0/1", 7, "high_traffic", "warning",
          "Traffic Gi0/1 trên R1 vượt 80% băng thông", 88, 80, False)
    alert("R2", "GigabitEthernet0/2", 9, "interface_down", "critical",
          "Interface Gi0/2 trên R2 bị down", None, None, False)
    alert("SW2", None, 14, "device_unreachable", "critical",
          "Không kết nối được SW2 (SSH timeout)", None, None, False)
    alert("SW1", "FastEthernet0/2", 38, "high_errors", "warning",
          "CRC tăng nhanh trên Fa0/2 của SW1", 120, 50, True)
    alert("R2", None, 50, "high_ram", "warning", "RAM R2 đạt 78%", 78, 75, True)

    con.commit()
    for tbl in ("devices", "interfaces", "metrics", "interface_stats", "alerts"):
        print(f"{tbl:16s} {con.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]} dòng")
    con.close()
    print(f"Đã tạo {args.db}")


if __name__ == "__main__":
    main()
