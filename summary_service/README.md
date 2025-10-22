# 摘要存档服务

独立于现有基金分�?Dash 应用�?Flask 服务，用于保存摘要输入与生成�?HTML，并提供 Web 页面展示�?REST API�?
## 功能

- 通过 `POST /api/summaries` 保存用户输入、相关网址、文件名以及 HTML 摘要�?- 自动将摘要写�?SQLite 数据库，并在 `stored_html/` 下生成静�?HTML 文件�?- 列表页面 `/` 展示所有摘要，详情页面可预览摘要并查看静态文件路径�?- `GET /api/summaries` �?`GET /api/summaries/<id>` 提供数据查询�?- `/summaries/<id>/render` 可直接以网页形式打开已保存的 HTML（无需额外服务）�?
## 环境与依�?
建议使用 Python 3.11（或兼容版本），推荐在独立的虚拟环境中安装依赖�?
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux / macOS

pip install flask
```

> 如果后续扩展需要，也可加入 `gunicorn` 等生产部署依赖�?
## 启动

```bash
cd summary_service
python app.py
```

启动后默认监�?`http://0.0.0.0:8050/`�?
- `http://<host>:8050/`：摘要列表页面�?- `http://<host>:8050/summaries/<id>`：摘要详情与预览�?- `http://<host>:8050/summaries/<id>/render`：直接渲�?HTML�?
静�?HTML 文件保存�?`summary_service/stored_html/`，即使服务停止亦可直接打开查看�?
## API

### `POST /api/summaries`

```json
{
  "user_input": "原始输入文本...",
  "urls": ["https://example.com"],
  "filenames": ["report.pdf"],
  "html_content": "<html>...</html>"
}
```

- **返回 201**�?
```json
{
  "id": 1,
  "detail_url": "http://<host>:8050/summaries/1",
  "render_url": "http://<host>:8050/summaries/1/render",
  "html_file": "D:\\...\\summary_service\\stored_html\\summary_20240527123456_xxx.html"
}
```

### `GET /api/summaries`

返回所有摘要的 JSON 列表�?
### `GET /api/summaries/<id>`

返回指定摘要的详�?JSON�?
## 部署提示

- 生产环境可使�?`gunicorn` �?`waitress` �?WSGI 服务器托管，再由 Nginx 做反向代理�?- 请确�?`data/` �?`stored_html/` 目录具备写入权限�?- 如需加入认证或访问控制，可在现有 Flask 应用基础上扩展�?
