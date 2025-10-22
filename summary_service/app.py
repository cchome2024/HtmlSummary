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
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "summaries.db"
HTML_DIR = BASE_DIR / "stored_html"


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
    urls = payload.get("urls") or []
    filenames = payload.get("filenames") or []
    if not isinstance(urls, list) or not isinstance(filenames, list):
        return _cors_headers(jsonify({"error": "urls and filenames must be lists"})), 400

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

    response = jsonify(
        {
            "id": summary_id,
            "detail_url": url_for("summary_detail", summary_id=summary_id, _external=True),
            "render_url": url_for("render_summary_html", summary_id=summary_id, _external=True),
            "html_file": str(html_path),
        }
    )
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
        return jsonify({"error": "Summary not found"}), 404
    record["detail_url"] = url_for("summary_detail", summary_id=summary_id, _external=True)
    record["render_url"] = url_for("render_summary_html", summary_id=summary_id, _external=True)
    record["html_file"] = str(HTML_DIR / record["html_filename"])
    return jsonify(record)


def fetch_record(summary_id: int) -> dict[str, Any] | None:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM summaries WHERE id = ?", (summary_id,)).fetchone()
    if row is None:
        return None
    return rows_to_records([row])[0]


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8050, debug=True)
