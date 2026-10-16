"""Chương trình thu thập chính.

Chạy từ thư mục gốc dự án:
    python -m collector.main                  # thu thập thật qua SSH, mỗi 15 giây
    python -m collector.main --mock --once    # thử với dữ liệu giả, chạy 1 chu kỳ
"""
import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from dotenv import load_dotenv

from alerts import engine
from collector.service import cleanup_old, collect_one, store_result, sync_devices
from db.database import connect, init_db

ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger("collector")


def parse_args():
    p = argparse.ArgumentParser(description="Network performance collector")
    p.add_argument("--config", help="file danh sách thiết bị (mặc định config/devices.yaml)")
    p.add_argument("--thresholds", default=str(ROOT / "config" / "thresholds.yaml"))
    p.add_argument("--interval", type=int, default=15, help="chu kỳ thu thập (giây)")
    p.add_argument("--workers", type=int, default=10, help="số thiết bị SSH song song")
    p.add_argument("--mock", action="store_true", help="dùng dữ liệu giả, không SSH")
    p.add_argument("--once", action="store_true", help="chỉ chạy 1 chu kỳ rồi thoát")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def load_devices(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        devices = yaml.safe_load(f)["devices"]
    for d in devices:
        if "hostname" not in d or "ip" not in d:
            sys.exit(f"Thiết bị thiếu hostname/ip: {d}")
    return devices


def run_cycle(con, devices, th, use_mock, workers):
    started = time.monotonic()
    ok = 0
    # Thread chỉ làm việc chậm (SSH + parse). Ghi DB làm tuần tự ở thread chính
    # vì SQLite chỉ cho 1 writer tại một thời điểm.
    with ThreadPoolExecutor(max_workers=min(workers, len(devices))) as pool:
        futures = {pool.submit(collect_one, d, use_mock): d for d in devices}
        for fut in as_completed(futures):
            dev, result = futures[fut], fut.result()
            try:
                store_result(con, dev, result, th)
                ok += result["ok"]
            except Exception:
                con.rollback()
                log.exception("[%s] lỗi khi ghi DB", dev["hostname"])
    log.info("Chu kỳ xong: %d/%d thiết bị OK (%.1fs)", ok, len(devices), time.monotonic() - started)


def main():
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    load_dotenv(ROOT / ".env")

    config = Path(args.config) if args.config else ROOT / "config" / "devices.yaml"
    if not config.exists():
        config = ROOT / "config" / "devices.example.yaml"
        log.warning("Chưa có config/devices.yaml, dùng %s", config.name)
    devices = load_devices(config)
    th = engine.load_thresholds(args.thresholds)

    if not args.mock and not (os.getenv("NET_USERNAME") and os.getenv("NET_PASSWORD")):
        sys.exit("Thiếu NET_USERNAME / NET_PASSWORD. Copy .env.example thành .env rồi điền vào.")

    init_db()
    con = connect()
    sync_devices(con, devices)
    log.info("Bắt đầu: %d thiết bị, chu kỳ %ds%s", len(devices), args.interval,
             " (MOCK)" if args.mock else "")

    next_cleanup = 0.0
    try:
        while True:
            started = time.monotonic()
            run_cycle(con, devices, th, args.mock, args.workers)
            if started >= next_cleanup:
                cleanup_old(con)
                next_cleanup = started + 3600
            if args.once:
                break
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log.info("Dừng collector")
    finally:
        con.close()


if __name__ == "__main__":
    main()
