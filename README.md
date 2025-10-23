# HtmlSummary Service

A lightweight backend service to upload files or input text, generate summaries in multiple formats (text, cards, flowchart, table), and return a rendered HTML page for viewing, downloading, or publishing via a public URL.

## Features

- Upload files or paste text
- Heuristic summarization (baseline, offline, multilingual-friendly)
- Output formats: Text, Card-style bullets, Mermaid flowchart, Table
- Returns an HTML page; also serves via public URL
- Built-in web UI at `/` for upload, configure, preview, and publish
- Optional browser-rendered URL fetching (Playwright) for sites requiring JS rendering (e.g., WeChat articles)
 - Or use Selenium + local Chrome/Chromium with session persistence to bypass one-time verification

## Quickstart

1. Create a virtual environment and install deps

```bash
python -m venv .venv
. .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

3. Try the API

- Health: `GET http://localhost:8000/health`
- Summarize: `POST http://localhost:8000/summarize`
  - Form fields:
    - `text` (optional): raw text or HTML/Markdown
    - `url` (optional): single or multiple URLs (comma/newline separated)
    - `files` (optional, multiple): `.txt`, `.md`, `.html`, `.pdf`, images (`.png/.jpg/.jpeg/.bmp/.tif/.tiff/.webp`)
    - `formats` (optional): comma-separated in {`text`,`cards`,`flowchart`,`table`}
    - `title` (optional): title for the output page
    - `length` (optional): target sentences for summary (default: 5)
    - `engine` (optional): `heuristic` (default) or `llm` (OpenAI-based)
    - `fetch_engine` (optional): `requests` (default) or `browser` (Playwright) or `selenium`
    - `referer` (optional): custom Referer header for direct fetching
    - `timeout` (optional): override direct-fetch timeout in seconds (default 12)
    - `headful` (optional): `1` to run a visible browser for manual verification (Playwright/Selenium)
    - `persist_session` (optional): `1` to remember cookies/session for the domain

Response JSON:

```json
{
  "result_id": "<uuid>",
  "view_url": "/public/<uuid>",
  "download_url": "/public/<uuid>?download=1"
}
```

Open `http://localhost:8000/public/<uuid>` to view the rendered HTML.

### Web UI
- Open `http://localhost:8000/` to use a simple upload and generation page.
- Supports: text input, URLs, file uploads, selecting formats, choosing `heuristic` or `llm` engine.
- After generation, previews the published HTML and shows the public link and a download button.

### Summary archive service (optional)
1. 启动原有 Flask 存档服务：`python summary_service/app.py`（默认监听 `http://127.0.0.1:8050`）。
2. 启动新的 MCP 存档服务：`python summary_mcp/app.py`（默认监听 `http://127.0.0.1:8150`）。
3. 在 `.env` 中分别设置 `SUMMARY_SERVICE_BASE_URL` 与 `SUMMARY_MCP_BASE_URL`，并重启 HtmlSummary。
4. 生成摘要后，预览面板会同时显示两个按钮：`保存摘要`（直接请求 Flask 服务）与 `通过 MCP 保存`（通过大模型 function call 触发 MCP 工具）。
5. 成功时状态栏会展示服务返回的详情/渲染链接；失败会提示错误但不会影响另一种保存方式。
6. 两种保存方式共享同一个 SQLite 数据库与 `stored_html/` 文件夹，列表/详情页面可互通查看。

### LLM-backed HTML generation

- JSON API: `POST /generate`

Request body:

```json
{
  "input_content": "用户上传的文件内容或手动输入的文?,
  "format": "text|card|flow|table",
  "title": "摘要的标?
}
```

Response:

```json
{
  "result_id": "<uuid>",
  "view_url": "/public/<uuid>",
  "download_url": "/public/<uuid>?download=1"
}
```

Environment variables (via `.env`):
- `LLM_PROVIDER` (default: `deepseek`, options: `deepseek` | `openai`)
- `LLM_API_KEY` (required for LLM)
- `LLM_MODEL` (default: `deepseek-chat` when provider=deepseek; `gpt-4o-mini` for openai)
- `LLM_BASE_URL` (default: `https://api.deepseek.com` for deepseek; unset for openai)

Setup with DeepSeek:
1. Copy `.env.example` to `.env`
2. Set `LLM_API_KEY` to your DeepSeek API key
3. (Optional) adjust `LLM_MODEL` (e.g., `deepseek-chat`)
4. Restart the server

## Notes

- This is a baseline heuristic summarizer to avoid external dependencies. You can plug in advanced models later.
- Supported file types: `.txt`, `.md`, `.html`, `.pdf`, images (`.png/.jpg/.jpeg/.bmp/.tif/.tiff/.webp`).
- Public files are written under `public/` and served by the app. They are not uploaded anywhere external.

### PDF
- Text is extracted using `pypdf`. Scanned/image-only PDFs may yield no text; consider converting to images or enabling OCR.

### Images (OCR)
- OCR uses `pytesseract` + `Pillow` and requires the Tesseract binary installed on the host.
- Optional install (not in default requirements):
  - Recommended: Python 3.11/3.12 on Windows, then `pip install pillow pytesseract`
  - Or use Conda: `conda install -c conda-forge pillow tesseract pytesseract`
  - On Windows with Python 3.14, prebuilt Pillow wheels may be unavailable; avoid building from source (zlib/toolchain needed). Prefer Python 3.12/3.11 or Conda.

### URL fetching
- Uses `requests` with a generic User-Agent and basic HTML stripping.
- Handle network egress and proxies as needed in your environment.
- Optional: set `referer` and `timeout` to adapt to stricter sites.

#### Browser-rendered fetching (Playwright)
- Install once: `pip install playwright` then `playwright install chromium`
- Enable by passing `fetch_engine=browser` or selecting it in the Web UI under URL settings.
- For human verification flows, check "可视化浏览器" and "记住会话" in the Web UI, complete verification once, and subsequent runs will reuse the stored session (under `storage/`).
- The service launches a headless Chromium to render the page, applies a mobile WeChat-like user agent and referer, scrolls to trigger lazy-load, and extracts the main content.
- Configure headless via env: `PLAYWRIGHT_HEADLESS=0` to run headful for debugging.
- Note: Running browsers is heavier; limit concurrency if deploying in production.

#### Browser-rendered fetching (Selenium + Chrome)
- Install: `pip install selenium undetected-chromedriver`
- Requires a local Chrome/Chromium installation. Set `CHROME_PATH` if auto-detection fails.
- Enable by passing `fetch_engine=selenium` or selecting it in the Web UI.
- Supports "可视化浏览器" (headful) and "记住会话"; cookies are stored under `storage/selenium-<domain>-cookies.json`.
- Headers: Uses CDP to set Referer/Accept-Language; sets a mobile WeChat-like UA and scrolls for lazy-load.

### Using LLM in `/summarize`
- Add `engine=llm` to make the service generate HTML using the LLM, respecting the selected formats. If multiple formats are requested, a wrapper page is produced embedding each LLM-generated HTML via `iframe srcdoc`.

## Example cURL

```bash
curl -X POST http://localhost:8000/summarize \
  -F "text=这是一个用于测试的示例文本。它包含多句话，用于演示摘要功能。服务会返回多种摘要形式并生成HTML文件? \
  -F "formats=text,cards,flowchart,table" \
  -F "title=示例摘要"
```

Upload a PDF and an image:

```bash
curl -X POST http://localhost:8000/summarize \
  -F files=@sample.pdf \
  -F files=@diagram.png \
  -F formats=text,cards
```

Summarize from URLs and text:

```bash
curl -X POST http://localhost:8000/summarize \
  -F "url=https://example.com/article, https://example.com/notes" \
  -F "text=补充说明：请按要点输出? \
  -F formats=text,table
```
