from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_from_directory,
    url_for,
)

BASE_DIR = Path(__file__).resolve().parent
SHARED_SERVICE_DIR = BASE_DIR.parent / "summary_service"
DATA_DIR = SHARED_SERVICE_DIR / "data"
DB_PATH = DATA_DIR / "summaries.db"
HTML_DIR = SHARED_SERVICE_DIR / "stored_html"


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    HTML_DIR.mkdir(parents=True, exist_ok=True)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_directories()
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                user_input TEXT,
                urls TEXT,
                filenames TEXT,
                html_content TEXT NOT NULL,
                html_filename TEXT NOT NULL
            )
            """
        )
        conn.commit()


def rows_to_records(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        def _loads(value: str | None) -> list[str]:
            if not value:
                return []
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []

        records.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "user_input": row["user_input"] or "",
                "urls": _loads(row["urls"]),
                "filenames": _loads(row["filenames"]),
                "html_content": row["html_content"],
                "html_filename": row["html_filename"],
            }
        )
    return records


def store_summary_entry(
    user_input: str,
    urls: list[str],
    filenames: list[str],
    html_content: str,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    html_filename = f"summary_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex}.html"
    html_path = HTML_DIR / html_filename
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_content, encoding="utf-8")

    urls_json = json.dumps(urls, ensure_ascii=False)
    filenames_json = json.dumps(filenames, ensure_ascii=False)

    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO summaries (created_at, user_input, urls, filenames, html_content, html_filename)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (created_at, user_input, urls_json, filenames_json, html_content, html_filename),
        )
        summary_id = cursor.lastrowid
        conn.commit()

    return {
        "id": summary_id,
        "created_at": created_at,
        "html_filename": html_filename,
        "html_path": html_path,
    }


def build_summary_result(meta: dict[str, Any]) -> dict[str, Any]:
    summary_id = meta["id"]
    html_filename = meta["html_filename"]
    html_path = meta["html_path"]
    result: dict[str, Any] = {
        "id": summary_id,
        "detail_url": url_for("summary_detail", summary_id=summary_id, _external=True),
        "render_url": url_for("render_summary_html", summary_id=summary_id, _external=True),
        "html_file": str(html_path),
    }
    created_at = meta.get("created_at")
    if created_at:
        result["created_at"] = created_at
    return result


def delete_summary_entry(summary_id: int) -> bool:
    record = fetch_record(summary_id)
    if record is None:
        return False
    file_path = HTML_DIR / record["html_filename"]
    if file_path.exists():
        try:
            file_path.unlink()
        except OSError:
            pass
    with get_db_connection() as conn:
        conn.execute("DELETE FROM summaries WHERE id = ?", (summary_id,))
        conn.commit()
    return True


def normalize_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    result: list[str] = []
    for item in value:
        if item is None:
            continue
        if not isinstance(item, str):
            item = str(item)
        result.append(item)
    return result


MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "save_summary",
        "description": "保存摘要 HTML 内容、相关网址及附件名称，并返回详情和渲染链接。",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_input": {"type": "string", "description": "用户的原始输入文本，可为空"},
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "相关网页链接列表，可为空列表",
                },
                "filenames": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "关联的本地文件名列表，可为空列表",
                },
                "html_content": {
                    "type": "string",
                    "description": "需要存档的完整 HTML 内容",
                },
                "title": {"type": "string", "description": "摘要标题（可选）"},
                "source_view_url": {"type": "string", "description": "原始预览地址（可选）"},
                "result_id": {"type": "string", "description": "前端生成的摘要 ID（可选）"},
            },
            "required": ["html_content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_summaries",
        "description": "列出已保存的摘要信息，可指定返回数量。",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回的最大数量（可选，默认返回全部）",
                    "minimum": 1,
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_summary",
        "description": "根据 ID 获取摘要的详细信息（包含 HTML 内容）。",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "摘要 ID"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_summary",
        "description": "根据 ID 删除摘要及对应的 HTML 文件。",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "摘要 ID"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


def mcp_tool_save_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    user_input = arguments.get("user_input", "")
    if not isinstance(user_input, str):
        user_input = str(user_input)
    urls = normalize_string_list(arguments.get("urls"), "urls")
    filenames = normalize_string_list(arguments.get("filenames"), "filenames")
    html_content = arguments.get("html_content")
    if not html_content or not isinstance(html_content, str):
        raise ValueError("html_content must be a non-empty string")
    meta = store_summary_entry(user_input, urls, filenames, html_content)
    result = build_summary_result(meta)
    # 附加可选信息，便于调用方回显
    optional_keys = ("title", "source_view_url", "result_id")
    for key in optional_keys:
        if arguments.get(key):
            result[key] = arguments[key]
    return result


def mcp_tool_list_summaries(arguments: dict[str, Any]) -> dict[str, Any]:
    limit = arguments.get("limit")
    query = "SELECT * FROM summaries ORDER BY datetime(created_at) DESC"
    params: tuple[Any, ...] = ()
    if limit is not None:
        if not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        query += " LIMIT ?"
        params = (limit,)
    with get_db_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    records = rows_to_records(rows)
    items: list[dict[str, Any]] = []
    for record in records:
        item = {
            "id": record["id"],
            "created_at": record["created_at"],
            "detail_url": url_for("summary_detail", summary_id=record["id"], _external=True),
            "render_url": url_for("render_summary_html", summary_id=record["id"], _external=True),
            "html_file": str(HTML_DIR / record["html_filename"]),
            "urls": record["urls"],
            "filenames": record["filenames"],
        }
        if record["user_input"]:
            item["user_input"] = record["user_input"]
        items.append(item)
    return {"items": items, "count": len(items)}


def mcp_tool_get_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    summary_id = arguments.get("id")
    if not isinstance(summary_id, int):
        raise ValueError("id must be an integer")
    record = fetch_record(summary_id)
    if record is None:
        raise ValueError("Summary not found")
    record["detail_url"] = url_for("summary_detail", summary_id=summary_id, _external=True)
    record["render_url"] = url_for("render_summary_html", summary_id=summary_id, _external=True)
    record["html_file"] = str(HTML_DIR / record["html_filename"])
    return record


def mcp_tool_delete_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    summary_id = arguments.get("id")
    if not isinstance(summary_id, int):
        raise ValueError("id must be an integer")
    if not delete_summary_entry(summary_id):
        raise ValueError("Summary not found")
    return {"status": "deleted", "id": summary_id}


def mcp_success(request_id: Any, result: Any):
    response = jsonify({"jsonrpc": "2.0", "id": request_id, "result": result})
    return _cors_headers(response)


def mcp_error(request_id: Any, code: int, message: str, http_status: int = 200):
    response = jsonify(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
    )
    wrapped = _cors_headers(response)
    return wrapped if http_status == 200 else (wrapped, http_status)

app = Flask(__name__, template_folder="templates")
app.config["JSON_SORT_KEYS"] = False

# Flask >= 3.0 removed before_first_request; ensure DB is created eagerly.
init_db()

def _cors_headers(response: Response) -> Response:
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    return response


def _cors_preflight() -> Response:
    response = Response(status=204)
    return _cors_headers(response)


@app.after_request
def add_cors(response: Response) -> Response:
    return _cors_headers(response)


@app.route("/")
def index() -> str:
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM summaries ORDER BY datetime(created_at) DESC"
        ).fetchall()
    records = rows_to_records(rows)
    for record in records:
        record["detail_url"] = url_for("summary_detail", summary_id=record["id"])
        record["render_url"] = url_for("render_summary_html", summary_id=record["id"])
    return render_template("index.html", records=records)


@app.route("/summaries/<int:summary_id>")
def summary_detail(summary_id: int) -> str:
    record = fetch_record(summary_id)
    if record is None:
        abort(404)
    record["render_url"] = url_for("render_summary_html", summary_id=summary_id)
    record["html_file_path"] = str(HTML_DIR / record["html_filename"])
    return render_template("summary.html", record=record)


@app.route("/summaries/<int:summary_id>/render")
def render_summary_html(summary_id: int):
    record = fetch_record(summary_id)
    if record is None:
        abort(404)
    filename = record["html_filename"]
    file_path = HTML_DIR / filename
    if file_path.exists():
        return send_from_directory(
            HTML_DIR,
            filename,
            mimetype="text/html",
            download_name=filename,
        )
    return Response(record["html_content"], mimetype="text/html")


@app.route("/api/summaries", methods=["POST", "OPTIONS"])
def create_summary():
    if request.method == "OPTIONS":
        return _cors_preflight()

    payload = request.get_json(force=True, silent=False)
    if payload is None:
        return _cors_headers(jsonify({"error": "Invalid JSON payload"})), 400

    html_content = payload.get("html_content")
    if not html_content:
        return _cors_headers(jsonify({"error": "html_content is required"})), 400

    user_input = payload.get("user_input", "")
    if not isinstance(user_input, str):
        user_input = str(user_input)
    try:
        urls = normalize_string_list(payload.get("urls"), "urls")
        filenames = normalize_string_list(payload.get("filenames"), "filenames")
    except ValueError as exc:
        return _cors_headers(jsonify({"error": str(exc)})), 400

    meta = store_summary_entry(user_input, urls, filenames, html_content)
    response_payload = build_summary_result(meta)
    response = jsonify(response_payload)
    return _cors_headers(response), 201


@app.route("/api/summaries", methods=["GET"])
def list_summaries():
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM summaries ORDER BY datetime(created_at) DESC"
        ).fetchall()
    records = rows_to_records(rows)
    for record in records:
        record["detail_url"] = url_for("get_summary", summary_id=record["id"], _external=True)
        record["render_url"] = url_for("render_summary_html", summary_id=record["id"], _external=True)
    return jsonify(records)


@app.route("/api/summaries/<int:summary_id>", methods=["GET"])
def get_summary(summary_id: int):
    record = fetch_record(summary_id)
    if record is None:
        return _cors_headers(jsonify({"error": "Summary not found"})), 404
    record["detail_url"] = url_for("summary_detail", summary_id=summary_id, _external=True)
    record["render_url"] = url_for("render_summary_html", summary_id=summary_id, _external=True)
    record["html_file"] = str(HTML_DIR / record["html_filename"])
    return _cors_headers(jsonify(record))


@app.route("/api/summaries/<int:summary_id>", methods=["DELETE", "OPTIONS"])
def delete_summary(summary_id: int):
    if request.method == "OPTIONS":
        return _cors_preflight()

    if not delete_summary_entry(summary_id):
        return _cors_headers(jsonify({"error": "Summary not found"})), 404
    return _cors_headers(jsonify({"status": "deleted", "id": summary_id}))


@app.route("/mcp", methods=["POST", "OPTIONS"])
def mcp_endpoint():
    if request.method == "OPTIONS":
        return _cors_preflight()

    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        return mcp_error(None, -32700, "Invalid JSON payload", http_status=400)

    if not isinstance(payload, dict):
        return mcp_error(None, -32600, "Invalid request", http_status=400)

    jsonrpc = payload.get("jsonrpc")
    request_id = payload.get("id")
    method = payload.get("method")

    if jsonrpc != "2.0" or not method:
        return mcp_error(request_id, -32600, "Invalid request", http_status=400)

    if method == "list_tools":
        return mcp_success(request_id, {"tools": MCP_TOOLS})

    if method == "call_tool":
        params = payload.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return mcp_error(request_id, -32602, "arguments must be an object")

        try:
            if name == "save_summary":
                result = mcp_tool_save_summary(arguments)
            elif name == "list_summaries":
                result = mcp_tool_list_summaries(arguments)
            elif name == "get_summary":
                result = mcp_tool_get_summary(arguments)
            elif name == "delete_summary":
                result = mcp_tool_delete_summary(arguments)
            else:
                return mcp_error(request_id, -32601, f"Unknown tool '{name}'")
        except ValueError as exc:
            return mcp_error(request_id, -32602, str(exc))
        except Exception as exc:  # pylint: disable=broad-except
            return mcp_error(request_id, -32000, f"Tool execution failed: {exc}", http_status=500)

        return mcp_success(request_id, result)

    return mcp_error(request_id, -32601, f"Unknown method '{method}'", http_status=400)


def fetch_record(summary_id: int) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM summaries WHERE id = ?", (summary_id,)).fetchone()
    if row is None:
        return None
    return rows_to_records([row])[0]


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8150, debug=True)
