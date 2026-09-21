# DỰ ÁN MINI: CỔNG NHẬP LIỆU DỮ LIỆU & NỘP LÊN MONGODB
## MLAI DECISION INTELLIGENCE PLATFORM

---

Dự án mini này cung cấp một **Giao diện Web trực quan (UI)** giúp bạn dễ dàng tự tay nhập các dữ liệu tri thức và nộp trực tiếp vào **MongoDB** (hoặc lưu trữ dự phòng cục bộ).

### 🌟 TÍNH NĂNG NỔI BẬT
1. **Giao diện chuẩn hóa theo Kiến trúc hệ thống**:
   * **Tab 1 - DB4 (Kinh nghiệm)**: Nhập tiêu đề, đúc kết ngắn gọn (`key_takeaway`), câu chuyện chi tiết.
   * **Tab 2 - DB3 (Vấn đề / Rủi ro)**: Nhập sự cố, mức độ nghiêm trọng (`HIGH / MEDIUM / LOW`), tóm tắt.
   * **Tab 3 - DB5 (Thị trường)**: Nhập phân khúc, ngân sách chi trả, thói quen tiêu dùng.
   * **Tab 4 - Yêu cầu Người Dùng**: Form thử nghiệm nhập kế hoạch kinh doanh của khách hàng.
   * **Tab 5 - Xem Dữ Liệu Đã Nộp**: Xem trực tiếp các bản ghi đã lưu trong MongoDB theo từng collection.
2. **Cơ chế Chọn Tag Chuẩn (Không cho nhập tự do)**:
   * Có sẵn nút tick chọn **[Tag 0] Quy tắc phổ quát** (áp dụng cho mọi ngành nghề).
   * Dropdown chọn **1 trong 10 Mô hình kinh doanh** (`101 - 110`).
   * Các nút bấm (Chips) chọn nhanh **Top 20 Sản phẩm/Dịch vụ phổ biến** (`201 - 220`).
3. **Cơ chế Auto-Fallback thông minh**:
   * Nếu máy bạn đã có MongoDB chạy trên `localhost:27017`, dữ liệu được lưu trực tiếp vào MongoDB Database: `mlai_decision_intelligence`.
   * Nếu bạn chưa cài MongoDB hoặc chưa bật MongoDB service, hệ thống **tự động lưu vào file JSON cục bộ** tại thư mục `mini_app/data/`, đảm bảo bạn nhập liệu mượt mà 100% không bao giờ bị lỗi!

---

### 🚀 HƯỚNG DẪN KHỞI CHẠY (CHỈ CẦN 1 LỆNH)

#### Bước 1: Mở Terminal tại thư mục `mini_app` và chạy:
```bash
python server.py
```
*(Server được viết bằng Python chuẩn, không cần cài đặt thêm thư viện bên ngoài).*

#### Bước 2: Mở trình duyệt Web
Truy cập vào địa chỉ:
👉 **[http://localhost:8000](http://localhost:8000)**

---

### ⚙️ CẤU HÌNH KẾT NỐI MONGODB TÙY CHỌN (NẾU DÙNG MONGODB ATLAS HOẶC PORT KHÁC)

Nếu bạn muốn nộp lên **MongoDB Atlas trên Cloud** hoặc cổng MongoDB khác, chỉ cần set biến môi trường trước khi chạy server:

**Trên Windows PowerShell:**
```powershell
$env:MONGO_URI="mongodb+srv://<username>:<password>@cluster.mongodb.net/?retryWrites=true&w=majority"
python server.py
```

**Trên Windows Command Prompt (CMD):**
```cmd
set MONGO_URI=mongodb://localhost:27017
python server.py
```

---

### 📂 CẤU TRÚC DỰ ÁN MINI
```
mini_app/
├── index.html      # Giao diện Web App (HTML5 + Tailwind CSS + FontAwesome)
├── server.py       # Web Server & REST API nộp dữ liệu lên MongoDB
├── README.md       # Tài liệu hướng dẫn sử dụng
└── data/           # Thư mục tự động lưu trữ dự phòng file JSON
    ├── experiences.json
    ├── problems.json
    ├── market_segments.json
    └── business_requests.json
```
