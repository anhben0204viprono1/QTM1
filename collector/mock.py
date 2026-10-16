"""Dữ liệu giả có định dạng giống Cisco IOS, để phát triển/kiểm thử khi chưa có lab."""
import random
import threading

from collector.errors import CollectError

_lock = threading.Lock()
_state: dict = {}

_INTERFACES = [  # (tên, mô tả, BW kbit, hoạt động?)
    ("GigabitEthernet0/0", "management", 1_000_000, True),
    ("GigabitEthernet0/1", "link to core", 1_000_000, True),
    ("GigabitEthernet0/2", "link to access", 1_000_000, True),
    ("GigabitEthernet0/3", None, 1_000_000, False),
]


def _block(name, desc, bw, admin, line, c):
    desc_line = f"  Description: {desc}\n" if desc else ""
    return (
        f"{name} is {admin}, line protocol is {line} \n"
        f"  Hardware is iGbE, address is aabb.cc00.0100 (bia aabb.cc00.0100)\n"
        f"{desc_line}"
        f"  MTU 1500 bytes, BW {bw} Kbit/sec, DLY 10 usec, \n"
        f"     reliability 255/255, txload 1/255, rxload 1/255\n"
        f"  Input queue: 0/75/0/0 (size/max/drops/flushes); Total output drops: {c['drops']}\n"
        f"  5 minute input rate 1000 bits/sec, 2 packets/sec\n"
        f"     {c['in_b'] // 100} packets input, {c['in_b']} bytes, 0 no buffer\n"
        f"     0 runts, 0 giants, 0 throttles\n"
        f"     {c['in_err']} input errors, {c['crc']} CRC, 0 frame, 0 overrun, 0 ignored\n"
        f"     {c['out_b'] // 100} packets output, {c['out_b']} bytes, 0 underruns\n"
        f"     {c['out_err']} output errors, 0 collisions, 1 interface resets\n"
    )


def fetch_raw_mock(dev: dict) -> dict:
    if dev.get("mock_fail"):
        raise CollectError("mock: thiết bị không phản hồi")

    with _lock:
        st = _state.setdefault(dev["ip"], {"tick": 0, "c": {
            n: {"in_b": 0, "out_b": 0, "in_err": 0, "crc": 0, "out_err": 0, "drops": 0}
            for n, *_ in _INTERFACES}})
        st["tick"] += 1
        tick = st["tick"]

        cpu = random.randint(82, 97) if random.random() < 0.10 else random.randint(4, 25)
        used_pct = random.uniform(86, 92) if random.random() < 0.05 else random.uniform(35, 60)
        total = 512 * 1024 * 1024
        used = int(total * used_pct / 100)

        blocks = []
        for name, desc, bw, active in _INTERFACES:
            c = st["c"][name]
            admin, line = ("up", "up") if active else ("administratively down", "down")
            if name.endswith("0/2") and tick % 8 in (5, 6):  # giả lập interface bị rớt
                admin, line = "down", "down"
            if active and line == "up":
                c["in_b"] += random.randint(50_000, 5_000_000)
                c["out_b"] += random.randint(50_000, 5_000_000)
                if name.endswith("0/1") and random.random() < 0.10:
                    c["in_b"] += 1_800_000_000  # burst ~ 960 Mbps
                if name.endswith("0/1") and random.random() < 0.08:
                    c["in_err"] += random.randint(60, 200)
                    c["crc"] += random.randint(10, 50)
            blocks.append(_block(name, desc, bw, admin, line, c))

    return {
        "cpu": f"CPU utilization for five seconds: {cpu}%/0%; one minute: {cpu}%; five minutes: {cpu}%",
        "mem": f"Processor Pool Total: {total} Used: {used} Free: {total - used}",
        "intf": "".join(blocks),
    }
