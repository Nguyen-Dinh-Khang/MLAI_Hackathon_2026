"""
server.py - Web Server phục vụ Giao diện Nhập liệu và Thao tác CRUD trực tiếp trên MongoDB.
Hỗ trợ:
- Xem / Liệt kê (List)
- Tìm kiếm & Lọc (Search & Filter) theo từ khóa, tag_ids, severity, model
- Thêm mới (Create)
- Chỉnh sửa (Update)
- Xóa (Delete)
Đảm bảo tính chuẩn hóa 100% cho 5 CSDL: areas, competitors, problems, experiences, market_segments.
"""

import os
import sys
import io
import json
import re
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

try:
    from bson import ObjectId
except ImportError:
    ObjectId = None

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
        "_id", "tag_ids", "price_range", "peak_hours", "interest", "demand",
        "segment", "price_tolerance", "peak_traffic", "behavior_notes", "embedding"
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


def build_id_filter(doc_id: str):
    """Tạo bộ lọc _id tương thích cả ObjectId và string thông thường."""
    if ObjectId and ObjectId.is_valid(doc_id):
        return {"$or": [{"_id": ObjectId(doc_id)}, {"_id": doc_id}]}
    return {"_id": doc_id}


# Tự động đọc file .env mà không cần cài thêm thư viện ngoài
def load_env_file():
    env_paths = [
        os.path.join(BASE_DIR, ".env"),
        os.path.join(os.path.dirname(BASE_DIR), ".env"),
        os.path.join(os.path.dirname(BASE_DIR), "mini_app", ".env")
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
DB_NAME = os.getenv("DB_NAME", "MLAI_Hackathon_2026")
mongo_client = None
mongo_db = None


def mask_uri(uri: str) -> str:
    """Che giấu mật khẩu trong URI khi log ra terminal."""
    return re.sub(r'://([^:]+):([^@]+)@', r'://\1:****@', uri)


def setup_database_indexes(db):
    """Thiết lập Index 2dsphere, tag_ids, severity và compound indexes trên MongoDB."""
    try:
        # DB1: Index không gian cho Khu vực
        db.areas.create_index([("center", "2dsphere")])
        
        # DB2: Index không gian và metadata cho Đối thủ
        db.competitors.create_index([("location", "2dsphere")])
        db.competitors.create_index([("business_model_id", 1)])
        db.competitors.create_index([("product_ids", 1)])
        db.competitors.create_index([("business_model_id", 1), ("product_ids", 1)])
        
        # DB3: Index tag_ids, severity và compound index
        db.problems.create_index([("tag_ids", 1)])
        db.problems.create_index([("severity", 1)])
        db.problems.create_index([("severity", 1), ("tag_ids", 1)])
        
        # DB4, DB5: Index cho mảng số tag_ids và interest
        db.experiences.create_index([("tag_ids", 1)])
        db.market_segments.create_index([("tag_ids", 1)])
        db.market_segments.create_index([("interest", -1)])
        
        print("[*] Đã cấu hình xong toàn bộ Indexes: 2dsphere, tag_ids, severity & compound!")
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


# =====================================================================
# CÁC HÀM XỬ LÝ JSON FALLBACK (KHI MẤT KẾT NỐI MONGODB)
# =====================================================================

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


def update_json_fallback(collection_name: str, doc_id: str, updated_fields: dict) -> bool:
    """Cập nhật bản ghi trong file JSON cục bộ."""
    file_path = os.path.join(DATA_DIR, f"{collection_name}.json")
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        found = False
        for item in data:
            if str(item.get("_id")) == str(doc_id):
                for k, v in updated_fields.items():
                    if k != "_id":
                        item[k] = v
                found = True
                break
        if found:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        return False
    except Exception as e:
        print(f"[!] Lỗi update JSON fallback: {e}")
        return False


def delete_json_fallback(collection_name: str, doc_id: str) -> bool:
    """Xóa bản ghi khỏi file JSON cục bộ."""
    file_path = os.path.join(DATA_DIR, f"{collection_name}.json")
    if not os.path.exists(file_path):
        return False
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        initial_len = len(data)
        data = [item for item in data if str(item.get("_id")) != str(doc_id)]
        if len(data) < initial_len:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        return False
    except Exception as e:
        print(f"[!] Lỗi delete JSON fallback: {e}")
        return False


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


# =====================================================================
# BỘ XỬ LÝ HTTP REQUEST (HỖ TRỢ FULL CRUD & SEARCH)
# =====================================================================

class MLAIHttpHandler(BaseHTTPRequestHandler):
    """Bộ xử lý HTTP Request phục vụ HTML và REST API CRUD + Search."""

    def _set_json_headers(self, status_code=200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
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
                "storage_mode": "MongoDB" if db is not None else "Local JSON",
                "database_name": DB_NAME
            }
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
            return

        # 3. API Lấy danh sách & Tìm kiếm / Lọc dữ liệu (Search & Filter)
        elif path in ["/api/documents", "/api/search"]:
            query_params = urllib.parse.parse_qs(parsed.query)
            col_name = query_params.get("collection", ["problems"])[0]
            search_query = query_params.get("q", [""])[0].strip()
            tag_filter = query_params.get("tag", [""])[0].strip()
            severity_filter = query_params.get("severity", [""])[0].strip()
            model_filter = query_params.get("model_id", [""])[0].strip()
            limit = int(query_params.get("limit", [100])[0])
            skip = int(query_params.get("skip", [0])[0])

            db = init_mongo_connection()
            docs = []
            total_count = 0

            if db is not None:
                try:
                    # Xây dựng bộ lọc MongoDB tự động
                    mongo_filter = {}

                    # Lọc theo Tag
                    if tag_filter:
                        try:
                            t_num = int(tag_filter)
                            if col_name == "competitors":
                                mongo_filter["product_ids"] = t_num
                            else:
                                mongo_filter["tag_ids"] = t_num
                        except ValueError:
                            pass

                    # Lọc theo Mức độ nghiêm trọng (Severity)
                    if severity_filter and col_name == "problems":
                        try:
                            s_num = int(severity_filter)
                            mongo_filter["severity"] = s_num
                        except ValueError:
                            mongo_filter["severity"] = severity_filter

                    # Lọc theo Mô hình kinh doanh
                    if model_filter and col_name in ["competitors", "business_requests"]:
                        try:
                            mongo_filter["business_model_id"] = int(model_filter)
                        except ValueError:
                            pass

                    # Lọc theo Từ khóa tìm kiếm (q) - Regex không phân biệt hoa thường
                    if search_query:
                        reg = {"$regex": re.escape(search_query), "$options": "i"}
                        or_fields = []
                        if col_name == "problems":
                            or_fields = [{"title": reg}, {"summary": reg}]
                        elif col_name == "experiences":
                            or_fields = [{"title": reg}, {"story": reg}, {"key_takeaway": reg}, {"dialogue_script": reg}]
                        elif col_name == "market_segments":
                            or_fields = [{"demand": reg}, {"segment": reg}, {"behavior_notes": reg}]
                        elif col_name == "competitors":
                            or_fields = [{"name": reg}, {"weakness": reg}, {"price_range": reg}]
                        elif col_name == "areas":
                            or_fields = [{"name": reg}, {"income_level": reg}]
                        elif col_name == "business_requests":
                            or_fields = [{"location_text": reg}, {"notes": reg}]
                        
                        if or_fields:
                            mongo_filter["$or"] = or_fields

                    total_count = db[col_name].count_documents(mongo_filter)
                    cursor = db[col_name].find(mongo_filter).sort("_id", -1).skip(skip).limit(limit)
                    
                    for d in cursor:
                        d["_id"] = str(d.get("_id"))
                        # Bổ sung cờ đánh dấu có vector embedding hay không để hiển thị trực quan
                        if "embedding" in d and isinstance(d["embedding"], list):
                            d["has_vector"] = len(d["embedding"]) > 0
                            d["vector_dim"] = len(d["embedding"])
                        docs.append(d)

                except Exception as err:
                    print(f"[!] Lỗi đọc từ MongoDB: {err}")
                    docs = get_from_json_fallback(col_name)
                    total_count = len(docs)
            else:
                docs = get_from_json_fallback(col_name)
                total_count = len(docs)

            self._set_json_headers(200)
            payload = {
                "collection": col_name,
                "total": total_count,
                "count": len(docs),
                "documents": docs
            }
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            return

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 1. API THÊM MỚI (CREATE)
        if path == "/api/submit":
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                post_body = self.rfile.read(content_len)
                data = json.loads(post_body.decode('utf-8'))

                collection_name = data.get("collection", "general")
                raw_document = data.get("document", {})

                # Lọc chuẩn hóa theo schema
                document = sanitize_document(collection_name, raw_document)

                # Mặc định embedding là mảng rỗng nếu chưa có
                if collection_name in ["problems", "experiences", "market_segments"]:
                    if "embedding" not in document or not isinstance(document.get("embedding"), list):
                        document["embedding"] = []

                inserted_id = None
                storage_target = "Local JSON Storage"

                db = init_mongo_connection()
                if db is not None:
                    try:
                        res = db[collection_name].insert_one(document)
                        inserted_id = str(res.inserted_id)
                        storage_target = "MongoDB Database"
                        print(f"[✓] Đã chèn vào MongoDB '{collection_name}': {inserted_id}")
                    except Exception as m_err:
                        print(f"[!] MongoDB Error ({m_err}), chuyển sang lưu file JSON...")
                        inserted_id = save_to_json_fallback(collection_name, document)
                else:
                    inserted_id = save_to_json_fallback(collection_name, document)
                    print(f"[✓] Đã lưu vào JSON fallback '{collection_name}': {inserted_id}")

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
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        # 2. API CHỈNH SỬA / CẬP NHẬT (UPDATE)
        elif path == "/api/update":
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                post_body = self.rfile.read(content_len)
                data = json.loads(post_body.decode('utf-8'))

                collection_name = data.get("collection")
                doc_id = str(data.get("id", "")).strip()
                raw_document = data.get("document", {})

                if not collection_name or not doc_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({"success": False, "error": "Thiếu collection hoặc id"}).encode("utf-8"))
                    return

                # Lọc dữ liệu theo schema
                sanitized = sanitize_document(collection_name, raw_document)
                if "_id" in sanitized:
                    del sanitized["_id"]

                db = init_mongo_connection()
                updated = False
                storage_target = "MongoDB Database"

                if db is not None:
                    id_filter = build_id_filter(doc_id)
                    # Nếu không gửi kèm embedding thì bảo lưu vector embedding cũ
                    if collection_name in ["problems", "experiences", "market_segments"]:
                        if "embedding" not in sanitized or not sanitized["embedding"]:
                            old_doc = db[collection_name].find_one(id_filter)
                            if old_doc and "embedding" in old_doc:
                                sanitized["embedding"] = old_doc["embedding"]

                    res = db[collection_name].update_one(id_filter, {"$set": sanitized})
                    updated = res.matched_count > 0 or res.modified_count > 0
                    print(f"[*] Cập nhật MongoDB '{collection_name}' ID {doc_id}: Matched={res.matched_count}, Modified={res.modified_count}")
                else:
                    storage_target = "Local JSON Fallback"
                    updated = update_json_fallback(collection_name, doc_id, sanitized)

                self._set_json_headers(200 if updated else 404)
                response = {
                    "success": updated,
                    "id": doc_id,
                    "storage": storage_target,
                    "message": "Cập nhật bản ghi thành công!" if updated else "Không tìm thấy bản ghi cần sửa."
                }
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        # 3. API XÓA (DELETE)
        elif path == "/api/delete":
            try:
                content_len = int(self.headers.get('Content-Length', 0))
                post_body = self.rfile.read(content_len)
                data = json.loads(post_body.decode('utf-8'))

                collection_name = data.get("collection")
                doc_id = str(data.get("id", "")).strip()

                if not collection_name or not doc_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({"success": False, "error": "Thiếu collection hoặc id"}).encode("utf-8"))
                    return

                db = init_mongo_connection()
                deleted = False
                storage_target = "MongoDB Database"

                if db is not None:
                    id_filter = build_id_filter(doc_id)
                    res = db[collection_name].delete_one(id_filter)
                    deleted = res.deleted_count > 0
                    print(f"[*] Xóa MongoDB '{collection_name}' ID {doc_id}: Deleted={res.deleted_count}")
                else:
                    storage_target = "Local JSON Fallback"
                    deleted = delete_json_fallback(collection_name, doc_id)

                self._set_json_headers(200 if deleted else 404)
                response = {
                    "success": deleted,
                    "id": doc_id,
                    "storage": storage_target,
                    "message": "Đã xóa bản ghi thành công khỏi MongoDB!" if deleted else "Không tìm thấy bản ghi để xóa."
                }
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode("utf-8"))
            return

        else:
            self.send_error(404, "Not Found")

    def do_PUT(self):
        """Hỗ trợ chuẩn RESTful PUT bằng cách gọi logic update."""
        self.path = "/api/update"
        self.do_POST()

    def do_DELETE(self):
        """Hỗ trợ chuẩn RESTful DELETE bằng cách gọi logic delete."""
        self.path = "/api/delete"
        self.do_POST()


def run_server():
    server_address = ("", PORT)
    httpd = HTTPServer(server_address, MLAIHttpHandler)
    print("\n" + "=" * 65)
    print(f"🚀 MLAI DATA INGESTION & MANAGEMENT SERVER ĐANG CHẠY TẠI:")
    print(f"👉 http://localhost:{PORT}")
    print(f"👉 http://127.0.0.1:{PORT}")
    print(f"🗄️  MongoDB Database: {DB_NAME}")
    print("=" * 65)
    print("Nhấn Ctrl + C để dừng máy chủ bất kỳ lúc nào.\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng máy chủ.")


if __name__ == "__main__":
    run_server()
