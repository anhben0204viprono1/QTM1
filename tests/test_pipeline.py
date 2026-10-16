import pytest

from collector.service import store_result, sync_devices
from db import database

TH = {
    "cpu_percent": {"warning": 80, "critical": 90},
    "ram_percent": {"warning": 85, "critical": 95},
    "traffic_percent": {"warning": 80, "critical": 95},
    "errors_delta": {"warning": 50},
}
DEV = {"hostname": "R1", "ip": "10.0.0.1"}
T0, T1, T2 = "2026-10-16T08:00:00Z", "2026-10-16T08:00:10Z", "2026-10-16T08:00:20Z"


@pytest.fixture
def con(tmp_path):
    path = tmp_path / "t.db"
    database.init_db(path)
    c = database.connect(path)
    sync_devices(c, [DEV])
    yield c
    c.close()


def ok(ts, cpu=10, octets=0, status="up", in_err=0):
    return {"ok": True, "ts": ts, "data": {
        "cpu": {"cpu_5s": cpu, "cpu_1m": cpu, "cpu_5m": cpu},
        "mem": {"ram_total_mb": 512, "ram_used_mb": 100, "ram_percent": 20},
        "interfaces": [{"name": "GigabitEthernet0/1", "description": "to R2", "speed_mbps": 1000,
                        "status": status, "in_octets": octets, "out_octets": octets,
                        "in_errors": in_err, "in_crc": 0, "out_errors": 0, "out_drops": 0}]}}


def open_alerts(con):
    return [(r["type"], r["severity"]) for r in
            con.execute("SELECT type, severity FROM alerts WHERE resolved = 0 ORDER BY type")]


def last_stats(con):
    return con.execute("SELECT * FROM interface_stats ORDER BY timestamp DESC LIMIT 1").fetchone()


def test_bps_from_delta(con):
    store_result(con, DEV, ok(T0, octets=0), TH)
    assert last_stats(con)["in_bps"] is None                      # mẫu đầu: chưa có delta
    store_result(con, DEV, ok(T1, octets=1_250_000), TH)          # 1.25 MB / 10 s = 1 Mbps
    assert last_stats(con)["in_bps"] == pytest.approx(1_000_000)


def test_counter_reset_gives_null(con):
    store_result(con, DEV, ok(T0, octets=5_000_000), TH)
    store_result(con, DEV, ok(T1, octets=100), TH)                # counter giảm = thiết bị reset
    assert last_stats(con)["in_bps"] is None


def test_cpu_alert_no_duplicates_then_resolve(con):
    for ts in (T0, T1, T2):
        store_result(con, DEV, ok(ts, cpu=95), TH)
    assert open_alerts(con) == [("high_cpu", "critical")]         # 3 chu kỳ vẫn chỉ 1 cảnh báo
    store_result(con, DEV, ok("2026-10-16T08:00:30Z", cpu=10), TH)
    assert open_alerts(con) == []
    assert con.execute("SELECT COUNT(*) FROM alerts WHERE resolved = 1").fetchone()[0] == 1


def test_severity_escalates_without_new_row(con):
    store_result(con, DEV, ok(T0, cpu=85), TH)
    assert open_alerts(con) == [("high_cpu", "warning")]
    store_result(con, DEV, ok(T1, cpu=95), TH)
    assert open_alerts(con) == [("high_cpu", "critical")]
    assert con.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1


def test_unreachable_and_recover(con):
    store_result(con, DEV, {"ok": False, "kind": "unreachable", "ts": T0, "error": "timeout"}, TH)
    assert con.execute("SELECT status FROM devices").fetchone()[0] == "down"
    assert open_alerts(con) == [("device_unreachable", "critical")]
    store_result(con, DEV, ok(T1), TH)
    assert con.execute("SELECT status FROM devices").fetchone()[0] == "up"
    assert open_alerts(con) == []


def test_interface_down_and_back_up(con):
    store_result(con, DEV, ok(T0, status="up"), TH)
    store_result(con, DEV, ok(T1, status="down"), TH)
    assert ("interface_down", "critical") in open_alerts(con)
    store_result(con, DEV, ok(T2, status="up"), TH)
    assert open_alerts(con) == []


def test_error_delta_alert(con):
    store_result(con, DEV, ok(T0, in_err=0), TH)
    store_result(con, DEV, ok(T1, in_err=100), TH)                # +100 > 50
    assert ("high_errors", "warning") in open_alerts(con)
    store_result(con, DEV, ok(T2, in_err=100), TH)                # +0
    assert open_alerts(con) == []


def test_high_traffic(con):
    store_result(con, DEV, ok(T0, octets=0), TH)
    store_result(con, DEV, ok(T1, octets=1_125_000_000), TH)      # 900 Mbps trên link 1 Gbps
    assert ("high_traffic", "warning") in open_alerts(con)
