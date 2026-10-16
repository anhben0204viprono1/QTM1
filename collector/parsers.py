"""Chuyển output lệnh `show` của Cisco IOS thành dict Python (dùng regex)."""
import re

from collector.errors import ParseError

# CPU utilization for five seconds: 5%/0%; one minute: 6%; five minutes: 5%
_CPU_RE = re.compile(
    r"five seconds:\s*(\d+)%(?:/\d+%)?;\s*one minute:\s*(\d+)%;\s*five minutes:\s*(\d+)%"
)
# Processor Pool Total:  249999132 Used:   62099044 Free:  187900088
_MEM_RE = re.compile(r"Processor Pool Total:\s*(\d+)\s+Used:\s*(\d+)\s+Free:\s*(\d+)")

# GigabitEthernet0/1 is up, line protocol is up
_HEAD_RE = re.compile(
    r"^(\S+) is (administratively down|up|down), line protocol is (up|down)", re.M
)
_BW_RE = re.compile(r"BW (\d+) Kbit")
_DESC_RE = re.compile(r"^\s*Description: (.*)$", re.M)
_IN_RE = re.compile(r"(\d+) packets input, (\d+) bytes")
_OUT_RE = re.compile(r"(\d+) packets output, (\d+) bytes")
_IN_ERR_RE = re.compile(r"(\d+) input errors, (\d+) CRC")
_OUT_ERR_RE = re.compile(r"(\d+) output errors")
_DROPS_RE = re.compile(r"Total output drops: (\d+)")


def parse_cpu(text: str) -> dict:
    m = _CPU_RE.search(text)
    if not m:
        raise ParseError(f"Không đọc được CPU: {text[:80]!r}")
    return {"cpu_5s": float(m.group(1)), "cpu_1m": float(m.group(2)), "cpu_5m": float(m.group(3))}


def parse_memory(text: str) -> dict:
    m = _MEM_RE.search(text)
    if not m:
        raise ParseError(f"Không đọc được RAM: {text[:80]!r}")
    total, used = int(m.group(1)), int(m.group(2))
    if total == 0:
        raise ParseError("RAM total = 0")
    mb = 1024 * 1024
    return {
        "ram_total_mb": round(total / mb, 1),
        "ram_used_mb": round(used / mb, 1),
        "ram_percent": round(used * 100 / total, 1),
    }


def map_status(admin: str, line: str) -> str:
    """Chuẩn hoá về 3 giá trị schema cho phép: up / down / admin_down."""
    if admin == "administratively down":
        return "admin_down"
    if admin == "up" and line == "up":
        return "up"
    return "down"


def _int(rx, text, group=1, default=0):
    m = rx.search(text)
    return int(m.group(group)) if m else default


def parse_interfaces(text: str) -> list[dict]:
    heads = list(_HEAD_RE.finditer(text))
    if not heads:
        raise ParseError(f"Không tìm thấy interface nào trong output: {text[:80]!r}")

    result = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        block = text[m.start():end]
        name = m.group(1)
        if name.startswith("Null"):
            continue

        bw = _BW_RE.search(block)
        desc = _DESC_RE.search(block)
        in_m, out_m = _IN_RE.search(block), _OUT_RE.search(block)
        result.append({
            "name": name,
            "description": desc.group(1).strip() if desc else None,
            "speed_mbps": round(int(bw.group(1)) / 1000) if bw else None,
            "status": map_status(m.group(2), m.group(3)),
            "in_octets": int(in_m.group(2)) if in_m else None,
            "out_octets": int(out_m.group(2)) if out_m else None,
            "in_errors": _int(_IN_ERR_RE, block, 1),
            "in_crc": _int(_IN_ERR_RE, block, 2),
            "out_errors": _int(_OUT_ERR_RE, block),
            "out_drops": _int(_DROPS_RE, block),
        })
    return result
