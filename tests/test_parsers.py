import pytest

from collector.errors import ParseError
from collector.parsers import parse_cpu, parse_interfaces, parse_memory

CPU = "CPU utilization for five seconds: 5%/0%; one minute: 6%; five minutes: 7%"
MEM = "Processor Pool Total:  249999132 Used:   62099044 Free:  187900088"

INTF = """GigabitEthernet0/0 is up, line protocol is up 
  Hardware is iGbE, address is 5000.0001.0000 (bia 5000.0001.0000)
  Description: management
  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec, 
  Input queue: 0/75/0/0 (size/max/drops/flushes); Total output drops: 3
     1500 packets input, 123456 bytes, 0 no buffer
     2 input errors, 1 CRC, 0 frame, 0 overrun, 0 ignored
     900 packets output, 654321 bytes, 0 underruns
     4 output errors, 0 collisions, 1 interface resets
GigabitEthernet0/1 is administratively down, line protocol is down 
  Hardware is iGbE, address is 5000.0001.0001 (bia 5000.0001.0001)
  MTU 1500 bytes, BW 1000000 Kbit/sec, DLY 10 usec, 
     0 packets input, 0 bytes, 0 no buffer
     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored
     0 packets output, 0 bytes, 0 underruns
     0 output errors, 0 collisions, 0 interface resets
GigabitEthernet0/2 is down, line protocol is down (notconnect) 
  MTU 1500 bytes, BW 100000 Kbit/sec, DLY 100 usec, 
     0 packets input, 0 bytes, 0 no buffer
     0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored
     0 packets output, 0 bytes, 0 underruns
     0 output errors, 0 collisions, 0 interface resets
Null0 is up, line protocol is up 
  MTU 1500 bytes, BW 8000000 Kbit/sec, DLY 5000 usec, 
"""


def test_cpu():
    assert parse_cpu(CPU) == {"cpu_5s": 5.0, "cpu_1m": 6.0, "cpu_5m": 7.0}


def test_cpu_invalid():
    with pytest.raises(ParseError):
        parse_cpu("% Invalid input detected")


def test_memory():
    m = parse_memory(MEM)
    assert m["ram_percent"] == pytest.approx(24.8, abs=0.1)
    assert m["ram_total_mb"] == pytest.approx(238.4, abs=0.1)


def test_interfaces():
    its = {i["name"]: i for i in parse_interfaces(INTF)}
    assert set(its) == {"GigabitEthernet0/0", "GigabitEthernet0/1", "GigabitEthernet0/2"}  # bỏ Null0
    g0 = its["GigabitEthernet0/0"]
    assert g0["status"] == "up" and g0["description"] == "management" and g0["speed_mbps"] == 1000
    assert (g0["in_octets"], g0["out_octets"]) == (123456, 654321)
    assert (g0["in_errors"], g0["in_crc"], g0["out_errors"], g0["out_drops"]) == (2, 1, 4, 3)
    assert its["GigabitEthernet0/1"]["status"] == "admin_down"
    assert its["GigabitEthernet0/2"]["status"] == "down"
    assert its["GigabitEthernet0/2"]["speed_mbps"] == 100


def test_interfaces_invalid():
    with pytest.raises(ParseError):
        parse_interfaces("% Invalid input")
