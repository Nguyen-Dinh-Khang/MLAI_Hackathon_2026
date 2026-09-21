"""
server.py - Web Server Mini phục vụ Giao diện Nhập liệu và Nộp dữ liệu lên MongoDB.
Chạy trực tiếp bằng Python tiêu chuẩn (Zero Dependency) với cơ chế tự động kết nối MongoDB
hoặc Auto-fallback sang Local JSON Storage nếu chưa cài pymongo / chưa bật MongoDB daemon.
"""

import os
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Cấu hình
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Tự động đọc file .env mà không cần cài thêm thư viện
def load_env_file():
    env_paths = [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.path.dirname(BASE_DIR), ".env")
    ]
    for p in env_paths:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip()
                            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                                v = v[1:-1]
                            os.environ[k] = v
                print(f"[*] Đã nạp cấu hình thành công từ file: {p}")
                return
            except Exception as err:
                print(f"[!] Không thể đọc file .env ({err})")

load_env_file()

# Cấu hình sau khi nạp .env
PORT = int(os.getenv("PORT", 8000))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "mlai_decision_intelligence")
mongo_client = None
mongo_db = None

# Thử kết nối MongoDB qua pymongo
try:
    from pymongo import MongoClient
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000)
    # Ping kiểm tra kết nối
    mongo_client.admin.command('ping')
    mongo_db = mongo_client[DB_NAME]
    print(f"[*] Kết nối thành công tới MongoDB: {MONGO_URI} (Database: {DB_NAME})")
except Exception as e:
    print(f"[!] Không thể kết nối MongoDB daemon ({e}).")
    print(f"[*] Hệ thống tự động kích hoạt chế độ: LOCAL JSON STORAGE tại: {DATA_DIR}")
    mongo_client = None
    mongo_db = None


def save_to_json_fallback(collection_name: str, document: dict) -> str:
    """Lưu dự phòng dữ liệu vào file JSON cục bộ."""
    file_path = os.path.join(DATA_DIR, f"{collection_name}.json")
    existing_data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            existing_data = []

    doc_id = f"loc_{int(datetime.now().timestamp() * 1000)}"
    document["_id"] = doc_id
    existing_data.insert(0, document)

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)

    return doc_id


def get_from_json_fallback(collection_name: str) -> list:
    """Lấy danh sách dữ liệu từ file JSON cục bộ."""
    file_path = os.path.join(DATA_DIR, f"{collection_name}.json")
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


class MLAIHttpHandler(BaseHTTPRequestHandler):
    """Bộ xử lý HTTP Request phục vụ HTML và REST API."""

    def _set_json_headers(self, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_json_headers(204)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. Trả về file giao diện index.html
        if path in ["/", "/index.html"]:
            html_path = os.path.join(BASE_DIR, "index.html")
            if os.path.exists(html_path):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                with open(html_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "File index.html not found")
            return

        # 2. API Health Check
        elif path == "/api/health":
            self._set_json_headers(200)
            status_data = {
                "status": "online",
                "mongo_connected": mongo_db is not None,
                "mongo_uri": MONGO_URI if mongo_db else "Using Local JSON Fallback",
                "storage_mode": "MongoDB" if mongo_db else "Local JSON"
            }
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
            return

        # 3. API Lấy danh sách tài liệu đã lưu
        elif path == "/api/documents":
            query_params = urllib.parse.parse_qs(parsed.query)
            col_name = query_params.get("collection", ["experiences"])[0]

            docs = []
            # Nếu có kết nối MongoDB thật
            if mongo_db is not None:
                try:
                    cursor = mongo_db[col_name].find().sort("_id", -1).limit(50)
                    for d in cursor:
                        d["_id"] = str(d.get("_id"))
                        docs.append(d)
                except Exception as err:
                    print(f"Lỗi đọc từ MongoDB: {err}")
                    docs = get_from_json_fallback(col_name)
            else:
                docs = get_from_json_fallback(col_name)

            self._set_json_headers(200)
            self.wfile.write(json.dumps({"collection": col_name, "documents": docs}, ensure_ascii=False).encode("utf-8"))
            return

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API Nộp dữ liệu lên MongoDB
        if path == "/api/submit":
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                post_body = self.rfile.read(content_len)
                data = json.loads(post_body.decode('utf-8'))

                collection_name = data.get("collection", "general")
                document = data.get("document", {})

                inserted_id = None
                storage_target = "Local JSON Storage"

                # 1. Thử lưu vào MongoDB
                if mongo_db is not None:
                    try:
                        res = mongo_db[collection_name].insert_one(document)
                        inserted_id = str(res.inserted_id)
                        storage_target = "MongoDB Database"
                        print(f"[OK] Đã chèn vào MongoDB '{collection_name}': {inserted_id}")
                    except Exception as m_err:
                        print(f"[!] MongoDB Error ({m_err}), chuyển sang lưu file JSON...")
                        inserted_id = save_to_json_fallback(collection_name, document)
                else:
                    # 2. Lưu vào file JSON
                    inserted_id = save_to_json_fallback(collection_name, document)
                    print(f"[OK] Đã lưu vào JSON fallback '{collection_name}': {inserted_id}")

                self._set_json_headers(200)
                response = {
                    "success": True,
                    "inserted_id": inserted_id,
                    "storage": storage_target,
                    "collection": collection_name,
                    "message": f"Dữ liệu đã được lưu thành công vào {storage_target}!"
                }
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))

            except Exception as e:
                self._set_json_headers(500)
                err_response = {"success": False, "error": str(e)}
                self.wfile.write(json.dumps(err_response).encode("utf-8"))
            return

        else:
            self.send_error(404, "Not Found")


def run_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, MLAIHttpHandler)
    print("\n" + "=" * 65)
    print(f"🚀 MLAI DATA INGESTION SERVER ĐANG CHẠY TẠI:")
    print(f"👉 http://localhost:{PORT}")
    print(f"👉 http://127.0.0.1:{PORT}")
    print("=" * 65)
    print("Nhấn Ctrl + C để dừng máy chủ bất kỳ lúc nào.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng máy chủ.")


if __name__ == "__main__":
    run_server()
