class CollectError(Exception):
    """Không kết nối / không lấy được dữ liệu từ thiết bị (timeout, sai mật khẩu...)."""


class ParseError(Exception):
    """Kết nối được nhưng output lệnh không đọc được (sai định dạng / lệnh không hỗ trợ)."""
