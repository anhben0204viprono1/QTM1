-- Schema DB: Dashboard giám sát hiệu suất mạng (SQLite)
-- Quy ước: timestamp lưu dạng ISO8601 UTC, ví dụ '2026-10-15T08:30:00Z'

PRAGMA foreign_keys = ON;

-- 1. Thiết bị
CREATE TABLE IF NOT EXISTS devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname     TEXT NOT NULL UNIQUE,
    ip           TEXT NOT NULL UNIQUE,
    vendor       TEXT,                       -- cisco, huawei, ...
    device_type  TEXT NOT NULL DEFAULT 'cisco_ios',  -- device_type của Netmiko
    status       TEXT NOT NULL DEFAULT 'unknown'
                 CHECK (status IN ('up', 'down', 'unknown')),
    last_seen    TEXT,                       -- lần thu thập thành công gần nhất
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- 2. CPU / RAM theo thời gian
CREATE TABLE IF NOT EXISTS metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    timestamp     TEXT NOT NULL,
    cpu_percent   REAL,
    ram_percent   REAL,
    ram_used_mb   REAL,
    ram_total_mb  REAL
);
CREATE INDEX IF NOT EXISTS idx_metrics_dev_time ON metrics(device_id, timestamp);

-- 3. Danh sách interface (thông tin tĩnh, mỗi interface 1 dòng)
CREATE TABLE IF NOT EXISTS interfaces (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,              -- GigabitEthernet0/1, ...
    description  TEXT,
    speed_mbps   INTEGER,
    UNIQUE (device_id, name)
);

-- 4. Số liệu interface theo thời gian
-- QUY ƯỚC: các cột bộ đếm (in_octets, out_octets, in_errors, in_crc, out_errors, out_drops)
-- lưu SỐ TÍCH LŨY đọc thẳng từ thiết bị (giống "show interface").
-- Khi cần số mới trong chu kỳ (ví dụ cảnh báo "lỗi tăng > N") thì tính delta
-- = giá trị lần này - giá trị lần trước. Nếu delta < 0 nghĩa là thiết bị reset bộ đếm
-- hoặc reboot: coi như delta = giá trị hiện tại (hoặc bỏ qua lần đó).
-- Riêng in_bps / out_bps là giá trị ĐÃ TÍNH, không phải bộ đếm.
CREATE TABLE IF NOT EXISTS interface_stats (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    interface_id  INTEGER NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
    timestamp     TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('up', 'down', 'admin_down')),
    in_octets     INTEGER,                   -- tích lũy, đơn vị byte
    out_octets    INTEGER,                   -- tích lũy, đơn vị byte
    in_bps        REAL,                      -- bit/giây = delta_octets * 8 / delta_giây
    out_bps       REAL,                      -- bit/giây (không phải byte/giây)
    in_errors     INTEGER DEFAULT 0,         -- input errors, tích lũy
    in_crc        INTEGER DEFAULT 0,         -- CRC errors, tích lũy
    out_errors    INTEGER DEFAULT 0,         -- output errors, tích lũy
    out_drops     INTEGER DEFAULT 0          -- output drops, tích lũy
);
CREATE INDEX IF NOT EXISTS idx_ifstats_if_time ON interface_stats(interface_id, timestamp);

-- 5. Cảnh báo
CREATE TABLE IF NOT EXISTS alerts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    interface_id  INTEGER REFERENCES interfaces(id) ON DELETE SET NULL,  -- NULL nếu là cảnh báo cấp thiết bị
    timestamp     TEXT NOT NULL,
    type          TEXT NOT NULL,             -- high_cpu, high_ram, high_traffic (> 80% băng thông),
                                             -- interface_down, device_unreachable,
                                             -- high_errors (delta lỗi/CRC/drops > N)
    severity      TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message       TEXT NOT NULL,
    value         REAL,                      -- giá trị đo được
    threshold     REAL,                      -- ngưỡng bị vượt
    resolved      INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
    resolved_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts(resolved, timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_dev ON alerts(device_id, resolved);

-- ===== View cho API của B =====

-- Số liệu CPU/RAM mới nhất của mỗi thiết bị (dùng cho /api/devices)
CREATE VIEW IF NOT EXISTS v_latest_metrics AS
SELECT m.*
FROM metrics m
JOIN (SELECT device_id, MAX(timestamp) AS ts FROM metrics GROUP BY device_id) x
  ON m.device_id = x.device_id AND m.timestamp = x.ts;

-- Số liệu mới nhất của mỗi interface (dùng cho /api/interfaces)
CREATE VIEW IF NOT EXISTS v_latest_interfaces AS
SELECT i.id AS interface_id, i.device_id, i.name, i.description, i.speed_mbps,
       s.timestamp, s.status, s.in_bps, s.out_bps,
       s.in_errors, s.in_crc, s.out_errors, s.out_drops   -- số tích lũy
FROM interfaces i
LEFT JOIN interface_stats s ON s.id = (
    SELECT id FROM interface_stats
    WHERE interface_id = i.id
    ORDER BY timestamp DESC LIMIT 1
);
