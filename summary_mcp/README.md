# 摘要存档 MCP 服务

该服务基于 Flask，兼顾原有网页界面，同时提供符合 MCP（Model Context Protocol）的工具接口，方便大模型通过 JSON-RPC 调用 `save_summary`、`list_summaries`、`get_summary`、`delete_summary` 等能力。与原有 `summary_service` 共用同一份 SQLite 数据库与 `stored_html/` 目录，因此无论通过哪个接口保存，都能在两个服务中互相看到。

## 主要特性
- Web UI：`/`、`/summaries/<id>`、`/summaries/<id>/render` 与旧版本一致，可直接查看和预览摘要。
- REST API：保留 `POST /api/summaries`、`GET /api/summaries`、`GET /api/summaries/<id>`、`DELETE /api/summaries/<id>`。
- MCP 接口：`POST /mcp`，遵循 JSON-RPC 2.0 协议，已内置以下工具：
  - `save_summary`
  - `list_summaries`
  - `get_summary`
  - `delete_summary`
- 摘要数据依旧写入 SQLite 数据库，静态 HTML 文件位于 `summary_mcp/stored_html/`。

## 环境与依赖
建议使用 Python 3.11+，并在独立虚拟环境中安装依赖：
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux / macOS
pip install flask
```

## 启动
```bash
cd summary_mcp
python app.py
```
默认监听 `http://0.0.0.0:8150/`，对应两个主要入口：
- `http://<host>:8150/`：摘要列表页
- `http://<host>:8150/summaries/<id>`：详情与预览

## MCP 调用示例
### 列出工具
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "list_tools"
}
```

### 保存摘要
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "call_tool",
  "params": {
    "name": "save_summary",
    "arguments": {
      "user_input": "原始输入...",
      "urls": ["https://example.com"],
      "filenames": ["report.pdf"],
      "html_content": "<html>...</html>"
    }
  }
}
```

### 删除摘要
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "call_tool",
  "params": {
    "name": "delete_summary",
    "arguments": { "id": 42 }
  }
}
```

## 目录说明
- `data/`：SQLite 数据库文件
- `stored_html/`：摘要 HTML 文件
- `templates/`：Web UI 模板

> 如需生产部署，可考虑搭配 `gunicorn`、`waitress` 等 WSGI 服务器，并确保 `data/`、`stored_html/` 拥有写权限。
