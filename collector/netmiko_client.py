"""Kết nối SSH bằng Netmiko và chạy lệnh show. Chạy trong thread của ThreadPoolExecutor."""
import logging
import os
import time

from collector.errors import CollectError

log = logging.getLogger("collector")

COMMANDS = {
    "cpu": "show processes cpu | include CPU utilization",
    "mem": "show processes memory | include Processor Pool",
    "intf": "show interfaces",
}


def fetch_raw(dev: dict, retries: int = 2) -> dict:
    """Trả về {"cpu": <text>, "mem": <text>, "intf": <text>} hoặc raise CollectError."""
    # import trễ để chế độ --mock và unit test chạy được mà không cần cài netmiko
    from netmiko import ConnectHandler
    from netmiko.exceptions import NetmikoAuthenticationException

    secret = os.getenv("NET_SECRET", "")
    params = {
        "device_type": dev.get("device_type", "cisco_ios"),
        "host": dev["ip"],
        "username": dev.get("username") or os.getenv("NET_USERNAME"),
        "password": dev.get("password") or os.getenv("NET_PASSWORD"),
        "secret": secret,
        "conn_timeout": 10,
        "auth_timeout": 10,
        "banner_timeout": 10,
    }

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with ConnectHandler(**params) as conn:
                if secret:
                    conn.enable()
                return {k: conn.send_command(cmd, read_timeout=30) for k, cmd in COMMANDS.items()}
        except NetmikoAuthenticationException as e:
            # Không thử lại khi sai mật khẩu để tránh khoá tài khoản
            raise CollectError(f"Sai tài khoản/mật khẩu: {e}") from e
        except Exception as e:  # timeout, connection refused, SSH algorithm...
            last_err = e
            log.warning("[%s] lần %d/%d thất bại: %s", dev["hostname"], attempt, retries, e)
            time.sleep(2)

    raise CollectError(f"Không kết nối được {dev['ip']}: {last_err}")
