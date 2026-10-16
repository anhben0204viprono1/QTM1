# Network Monitoring Dashboard (starter)

Stack: FastAPI + SQLite + React/Vite + Chart.js.

## 1. Đặt Database hiện tại

Copy file SQLite đang có vào `backend/data/network.db`.
Không chạy lại `schema-2.sql` nếu Database đã có bảng và dữ liệu mẫu.
Nếu file DB đang ở chỗ khác, thiết lập biến `DATABASE_PATH` trước khi chạy backend.

## 2. Chạy backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate       # macOS/Linux
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Mở `http://127.0.0.1:8000/api/health` trước. Kiểm tra `status`, `counts` và `database_path`.
Mở `http://127.0.0.1:8000/docs` để thử các API.

Nếu file DB ở vị trí khác:

```bash
# macOS/Linux, thay bằng đường dẫn thật
export DATABASE_PATH="/duong/dan/thuc/te/network.db"
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

PowerShell:

```powershell
$env:DATABASE_PATH="C:\duongdan\network.db"
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## 3. Kiểm tra API

- `GET /api/health`
- `GET /api/devices`
- `GET /api/metrics?limit=100`
- `GET /api/interfaces`
- `GET /api/alerts?resolved=0`

## 4. Chạy React

Mở terminal thứ hai:

```bash
cd frontend
npm install
npm run dev
```

Mở `http://localhost:5173`.

## Ghi chú

- Giao diện refresh API mỗi 5 giây; đây không phải chu kỳ thu thập dữ liệu từ thiết bị.
- API `/api/metrics` trả tối đa 100 bản ghi gần nhất mặc định, sắp xếp tăng dần thời gian sau khi truy vấn để vẽ biểu đồ.
- Nếu health báo thiếu bảng hoặc API báo thiếu View, kiểm tra xem DB thực tế đã được tạo từ schema đầy đủ chưa.
- `status` của thiết bị phụ thuộc vào collector cập nhật bảng `devices`. Dashboard không tự ping thiết bị.
- Traffic hiển thị theo `in_bps`/`out_bps` đã được collector tính toán.
