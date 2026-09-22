"""
server.py - Web Server phục vụ Giao diện Nhập liệu và Nộp dữ liệu lên MongoDB.
Đảm bảo tính chuẩn hóa 100% cho 5 CSDL: areas, competitors, problems, experiences, market_segments.
Không cho phép lưu bất kỳ trường dư thừa nào ngoài đặc tả.
"""

import os
import sys
import io
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Đảm bảo in tiếng Việt trên console Windows không bị UnicodeEncodeError
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Cấu hình đường dẫn
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ĐẶC TẢ THUỘC TÍNH CHUẨN XÁC 100% CHO TỪNG COLLECTION (KHÔNG DƯ TRƯỜNG NÀO)
STRICT_COLLECTION_SCHEMAS = {
    "areas": {
        "_id", "name", "center", "radius_m", "population_density", 
        "age_distribution", "income_level", "area_type"
    },
    "competitors": {
        "_id", "name", "location", "business_model_id", "product_ids", 
        "price_range", "rating", "review_count", "weakness"
    },
    "problems": {
        "_id", "tag_ids", "title", "summary", "severity", "embedding"
    },
    "experiences": {
        "_id", "tag_ids", "title", "story", "key_takeaway", "dialogue_script", "embedding"
    },
    "market_segments": {
        "_id", "tag_ids", "segment", "price_tolerance", "peak_traffic", "behavior_notes", "embedding"
    },
    "business_requests": {
        "_id", "location_text", "business_model_id", "product_ids", 
        "budget", "target_customer", "rent", "notes"
    }
}


def sanitize_document(collection_name: str, document: dict) -> dict:
    """
    Bộ lọc nghiêm ngặt: Loại bỏ 100% các trường nằm ngoài danh sách thuộc tính cho phép.
    """
    allowed_fields = STRICT_COLLECTION_SCHEMAS.get(collection_name)
    if not allowed_fields:
        return document
    return {k: v for k, v in document.items() if k in allowed_fields}


# Tự động đọc file .env mà không cần cài thêm thư viện ngoài
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

PORT = int(os.getenv("PORT", 8000))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "mlai_decision_intelligence")
mongo_client = None
mongo_db = None


def mask_uri(uri: str) -> str:
    """Che giấu mật khẩu trong URI khi log ra terminal."""
    import re
    return re.sub(r'://([^:]+):([^@]+)@', r'://\1:****@', uri)


def setup_database_indexes(db):
    """Thiết lập Index 2dsphere (Không gian) và Tag Index trên MongoDB."""
    try:
        # DB1: Index không gian cho Khu vực
        db.areas.create_index([("center", "2dsphere")])
        # DB2: Index không gian cho Đối thủ
        db.competitors.create_index([("location", "2dsphere")])
        # DB3, DB4, DB5: Index cho mảng số tag_ids
        db.problems.create_index([("tag_ids", 1)])
        db.experiences.create_index([("tag_ids", 1)])
        db.market_segments.create_index([("tag_ids", 1)])
        print("[*] Đã cấu hình xong toàn bộ Indexes: 2dsphere (DB1, DB2) & tag_ids (DB3, DB4, DB5)!")
    except Exception as idx_err:
        print(f"[!] Cảnh báo tạo index: {idx_err}")


def init_mongo_connection():
    """Khởi tạo hoặc kiểm tra kết nối MongoDB."""
    global mongo_client, mongo_db
    if mongo_db is not None:
        return mongo_db
    try:
        from pymongo import MongoClient
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        mongo_client = client
        mongo_db = client[DB_NAME]
        print(f"[*] Kết nối THÀNH CÔNG tới MongoDB: {mask_uri(MONGO_URI)} (DB: {DB_NAME})")
        setup_database_indexes(mongo_db)
        return mongo_db
    except Exception as e:
        print(f"[!] Không thể kết nối MongoDB daemon ({e}).")
        print(f"[*] Hệ thống kích hoạt chế độ dự phòng: LOCAL JSON STORAGE tại: {DATA_DIR}")
        return None


# Kiểm tra kết nối MongoDB khi khởi động
init_mongo_connection()


def save_to_json_fallback(collection_name: str, document: dict) -> str:
    """Lưu dự phòng dữ liệu vào file JSON cục bộ chuẩn hóa."""
    file_path = os.path.join(DATA_DIR, f"{collection_name}.json")
    existing_data = []
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        except Exception:
            existing_data = []

    if "_id" not in document or not document["_id"]:
        prefix_map = {
            "areas": "area",
            "competitors": "comp",
            "problems": "prob",
            "experiences": "exp",
            "market_segments": "mkt",
            "business_requests": "req"
        }
        p = prefix_map.get(collection_name, "doc")
        document["_id"] = f"{p}_{int(datetime.now().timestamp() * 1000)}"

    doc_id = str(document["_id"])
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
    """Bộ xử lý HTTP Request phục vụ HTML và REST API chuẩn."""

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
            db = init_mongo_connection()
            self._set_json_headers(200)
            status_data = {
                "status": "online",
                "mongo_connected": db is not None,
                "mongo_uri": mask_uri(MONGO_URI) if db is not None else "Using Local JSON Fallback",
                "storage_mode": "MongoDB" if db is not None else "Local JSON"
            }
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
            return

        # 3. API Lấy danh sách tài liệu đã lưu
        elif path == "/api/documents":
            query_params = urllib.parse.parse_qs(parsed.query)
            col_name = query_params.get("collection", ["experiences"])[0]

            db = init_mongo_connection()
            docs = []
            if db is not None:
                try:
                    cursor = db[col_name].find().sort("_id", -1).limit(50)
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
                raw_document = data.get("document", {})

                # LỌC NGHIÊM NGẶT THEO ĐẶC TẢ (KHÔNG CHO PHÉP DƯ BẤT KỲ TRƯỜNG NÀO)
                document = sanitize_document(collection_name, raw_document)

                # Mặc định embedding là mảng rỗng cho DB3, DB4, DB5
                if collection_name in ["problems", "experiences", "market_segments"]:
                    if "embedding" not in document or not isinstance(document.get("embedding"), list):
                        document["embedding"] = []

                inserted_id = None
                storage_target = "Local JSON Storage"

                # 1. Thử lưu vào MongoDB
                db = init_mongo_connection()
                if db is not None:
                    try:
                        res = db[collection_name].insert_one(document)
                        inserted_id = str(res.inserted_id)
                        storage_target = "MongoDB Database"
                        print(f"[OK] Đã chèn vào MongoDB '{collection_name}': {inserted_id}")
                    except Exception as m_err:
                        print(f"[!] MongoDB Error ({m_err}), chuyển sang lưu file JSON...")
                        inserted_id = save_to_json_fallback(collection_name, document)
                else:
                    # 2. Lưu vào file JSON cục bộ
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
