import json
import os
import uuid
import logging
import traceback
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from .io_utils import ensure_public_dir, load_text_from_upload, merge_texts, fetch_text_from_url
from .browser_fetch import fetch_text_via_playwright, BrowserFetchError
from .selenium_fetch import fetch_text_via_selenium
from .summarizer import (
    build_html_document,
    render_cards_summary,
    render_mermaid_flowchart,
    render_table_summary,
    render_text_summary,
)
from .llm_client import DEFAULT_PROMPTS, generate_html_with_llm


DEBUG_ERRORS = bool(os.getenv("DEBUG_ERRORS", "").strip())

app = FastAPI(title="HtmlSummary Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = ensure_public_dir(BASE_DIR)
SUMMARY_SERVICE_URL = (os.getenv("SUMMARY_SERVICE_BASE_URL") or "http://127.0.0.1:8050").rstrip("/")

# Logger
logger = logging.getLogger("htmlsummary")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_handler)
logger.setLevel(getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    payload = {"detail": "Internal Server Error"}
    if DEBUG_ERRORS:
        payload.update({"error": str(exc), "trace": traceback.format_exc()})
    return JSONResponse(status_code=500, content=payload)


@app.get("/")
def index():
    # UI-only markup. Chinese text is encoded in UTF-8.
    prompts_json = json.dumps(DEFAULT_PROMPTS, ensure_ascii=False)
    html = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>HtmlSummary · 生成与发布摘要</title>
  <style>
    *,*::before,*::after{ box-sizing:border-box }
    :root{ --bg:#0b1020; --panel:#0f1629; --panel-2:#121a31; --ink:#e5e7eb; --sub:#9aa4b2; --border:#23314f; --accent:#5b9dff; --accent-2:#7dd3fc; --ring:0 0 0 3px rgba(91,157,255,.25); }
    [data-theme="light"]{ --bg:#f6f8fb; --panel:#ffffff; --panel-2:#f9fafb; --ink:#0f172a; --sub:#475569; --border:#e5e7eb; --accent:#2563eb; --accent-2:#06b6d4; --ring:0 0 0 3px rgba(37,99,235,.2); }
    html,body{height:100%}
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,Helvetica,sans-serif;color:var(--ink);margin:0;background:var(--bg)}
    .topbar{position:sticky;top:0;z-index:10;background:linear-gradient(90deg,var(--panel),var(--panel-2));border-bottom:1px solid var(--border)}
    .topbar .inner{max-width:1100px;margin:0 auto;padding:12px 24px;display:flex;align-items:center;justify-content:space-between}
    .brand{display:flex;align-items:center;gap:10px;font-weight:700}
    .brand .logo{width:28px;height:28px;border-radius:8px;background:linear-gradient(135deg,var(--accent),var(--accent-2));box-shadow:0 8px 20px rgba(0,0,0,.2)}
    .wrap{max-width:1100px;margin:24px auto;padding:0 24px;overflow-x:hidden}
    h1{font-size:22px;margin:0 0 8px}
    .card{border:1px solid var(--border);border-radius:14px;padding:16px;background:var(--panel);box-shadow:0 6px 24px rgba(0,0,0,.12)}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
    label{font-weight:600;display:block;margin:12px 0 6px}
    input[type=text],input[type=number],textarea,select{width:100%;max-width:100%;padding:12px;border:1px solid var(--border);border-radius:12px;font:inherit;background:var(--panel-2);color:var(--ink);overflow-wrap:anywhere;word-break:break-word}
    input:focus,textarea:focus,select:focus{outline:none;box-shadow:var(--ring);border-color:var(--accent)}
    textarea{min-height:140px}
    .muted{color:var(--sub);font-size:12px}
    .row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
    .btn{appearance:none;cursor:pointer;border:1px solid var(--border);background:var(--accent);color:#fff;border-radius:12px;padding:10px 16px;font-weight:700;letter-spacing:.2px}
    .btn:hover{filter:brightness(1.05)}
    .btn.secondary{background:transparent;color:var(--ink)}
    .status{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border:1px solid var(--border);border-radius:999px;background:var(--panel-2)}
    .bad{color:#fca5a5}.good{color:#10b981}.warn{color:#f59e0b}
    .formats{display:flex;gap:12px;flex-wrap:wrap}
    .formats label{font-weight:500;margin:0}
    .preview{margin-top:16px}
    iframe{width:100%;height:560px;border:1px solid var(--border);border-radius:14px;background:var(--panel-2);box-shadow:0 10px 30px rgba(0,0,0,.2)}
    .links{display:flex;gap:12px;align-items:center;margin-top:8px}
    .hint{background:var(--panel-2);border:1px dashed var(--border);padding:10px;border-radius:12px;margin-top:8px;color:var(--sub)}
    .pill{display:inline-flex;gap:8px;align-items:center;padding:8px 12px;border:1px solid var(--border);border-radius:999px;background:var(--panel-2)}
    .switch{appearance:none;position:relative;width:46px;height:26px;border-radius:999px;background:var(--border);outline:none;border:none;cursor:pointer}
    .switch::after{content:"";position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:all .2s ease}
    .switch.active{background:var(--accent)}.switch.active::after{left:23px}
    #llmPromptBlock{margin-top:18px}
    #llmPromptBlock textarea{min-height:140px}
    @media (max-width: 980px){ .grid{ grid-template-columns:1fr } iframe{ height: 460px } }
  </style>
  <script>
    const THEME_KEY='hs_theme';
    const DEFAULT_PROMPTS = __PROMPTS_PLACEHOLDER__;
    const SUMMARY_SERVICE_BASE_RAW = __SUMMARY_SERVICE_URL__;
    const SUMMARY_SERVICE_BASE = typeof SUMMARY_SERVICE_BASE_RAW === 'string' ? SUMMARY_SERVICE_BASE_RAW.replace(/\\/+$/, '') : '';
    const summaryServiceAvailable = SUMMARY_SERVICE_BASE.length > 0;
    let lastSummaryPayload = null;
    let summaryFormSnapshot = null;
    let isSavingSummary = false;
    const promptCache = Object.assign({}, DEFAULT_PROMPTS);
    let promptDirty = false;
    function applyTheme(t){document.documentElement.setAttribute('data-theme',t);const s=document.getElementById('themeSwitch');if(s){s.classList.toggle('active',t==='dark');}}
    function initTheme(){const t=localStorage.getItem(THEME_KEY)||'dark';applyTheme(t);} 
    function toggleTheme(){const cur=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';localStorage.setItem(THEME_KEY,cur);applyTheme(cur);} 
    function getSelectedFormat(){
      const form = document.getElementById('f');
      if (!form){ return 'text'; }
      const radio = form.querySelector('input[name="format_choice"]:checked');
      return radio ? radio.value : 'text';
    }
    function setPromptValue(value, markAuto){
      const textarea = document.getElementById('llm_prompt');
      if (!textarea){ return; }
      textarea.value = value;
      if (markAuto){
        const fmt = getSelectedFormat();
        promptCache[fmt] = value;
        promptDirty = false;
      }
    }
    function ensurePromptForFormat(force){
      const form = document.getElementById('f');
      const block = document.getElementById('llmPromptBlock');
      const textarea = document.getElementById('llm_prompt');
      if (!form || !block || !textarea){ return; }
      const engine = form.engine.value || 'heuristic';
      if (engine === 'llm'){
        block.style.display = '';
        const fmt = getSelectedFormat();
        const tpl = promptCache[fmt] || DEFAULT_PROMPTS[fmt] || '';
        if (force || !promptDirty){
          setPromptValue(tpl, true);
        }
      } else {
        block.style.display = 'none';
      }
    }
    function initForm(){
      const form = document.getElementById('f');
      if (!form){ return; }
      const promptField = document.getElementById('llm_prompt');
      if (promptField){
        promptField.addEventListener('input', ()=>{
          promptDirty = true;
          const fmt = getSelectedFormat();
          promptCache[fmt] = promptField.value;
        });
      }
      form.engine.addEventListener('change', ()=>{
        ensurePromptForFormat(false);
      });
      form.querySelectorAll('input[name="format_choice"]').forEach(radio=>{
        radio.addEventListener('change', ()=>{
          if (document.getElementById('f').engine.value === 'llm'){
            ensurePromptForFormat(true);
          } else {
            ensurePromptForFormat(false);
          }
        });
      });
      ensurePromptForFormat(false);
      resetSaveState();
    }
    function captureFormSnapshot(){
      const form = document.getElementById('f');
      if (!form){ return null; }
      const text = (form.text.value || '').trim();
      const title = (form.title.value || '').trim() || '内容摘要';
      const rawUrl = form.url.value || '';
      const urls = rawUrl.split(/[\\n,]/).map((item)=>item.trim()).filter(Boolean);
      const fileInput = form.files;
      const fileList = fileInput && fileInput.files ? Array.from(fileInput.files) : [];
      const filenames = fileList.map((file)=>file.name);
      return { text, title, urls, filenames };
    }
    function getSaveButton(){
      return document.getElementById('saveSummary');
    }
    function updateSaveButton(canSave){
      const btn = getSaveButton();
      if (!btn){ return; }
      const enable = summaryServiceAvailable && canSave && !isSavingSummary;
      btn.disabled = !enable;
      if (!summaryServiceAvailable){
        btn.title = '未配置摘要存档服务';
      } else if (!canSave){
        btn.title = '请先生成摘要';
      } else {
        btn.title = '';
      }
      if (!enable && !isSavingSummary){
        btn.textContent = '保存摘要';
      }
    }
    function setSaveBusy(busy){
      const btn = getSaveButton();
      if (!btn){ return; }
      if (busy){
        btn.disabled = true;
        btn.textContent = '保存中...';
      } else {
        btn.textContent = '保存摘要';
        updateSaveButton(Boolean(lastSummaryPayload && summaryFormSnapshot));
      }
    }
    function resetSaveState(){
      lastSummaryPayload = null;
      summaryFormSnapshot = null;
      updateSaveButton(false);
    }
    async function saveSummary(){
      if (!summaryServiceAvailable){
        const status = document.getElementById('status');
        if (status){
          status.textContent = '未配置摘要存档服务';
          status.className = 'warn';
        }
        return;
      }
      if (!lastSummaryPayload || !summaryFormSnapshot){
        const status = document.getElementById('status');
        if (status){
          status.textContent = '请先生成摘要';
          status.className = 'warn';
        }
        return;
      }
      if (isSavingSummary){
        return;
      }
      isSavingSummary = true;
      setSaveBusy(true);
      try{
        const viewUrl = lastSummaryPayload.view_url_absolute || (location.origin + lastSummaryPayload.view_url);
        const htmlRes = await fetch(viewUrl);
        if (!htmlRes.ok){
          throw new Error('无法获取摘要 HTML');
        }
        const htmlContent = await htmlRes.text();
        const payload = {
          user_input: summaryFormSnapshot.text,
          urls: summaryFormSnapshot.urls,
          filenames: summaryFormSnapshot.filenames,
          html_content: htmlContent,
          title: summaryFormSnapshot.title,
          source_view_url: viewUrl,
          result_id: lastSummaryPayload.result_id || ''
        };
        const response = await fetch(`${SUMMARY_SERVICE_BASE}/api/summaries`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await response.json().catch(()=>null);
        if (!response.ok){
          const message = data && (data.error || data.detail) ? (data.error || data.detail) : `保存失败（${response.status}）`;
          throw new Error(message);
        }
        const status = document.getElementById('status');
        if (status){
          status.textContent = data && data.detail_url ? `摘要已保存：${data.detail_url}` : '摘要已保存';
          status.className = 'good';
        }
      }catch(err){
        const status = document.getElementById('status');
        if (status){
          status.textContent = (err && err.message) ? err.message : '保存摘要失败';
          status.className = 'bad';
        }
      }finally{
        isSavingSummary = false;
        setSaveBusy(false);
      }
    }
    async function submitForm(ev){
      ev.preventDefault();
      resetSaveState();
      const form = document.getElementById('f');
      const fd = new FormData();
      const text = form.text.value.trim();
      const url = form.url.value.trim();
      const title = form.title.value.trim() || '内容摘要';
      const length = form.length.value || '5';
      const engine = form.engine.value || 'heuristic';
      if (!text && !url && !form.files.files.length){ return showError('请提供文本、URL 或上传文件'); }
      const format = getSelectedFormat();
      if (!format){ return showError('请选择输出格式'); }
      fd.append('format', format);
      fd.append('formats', format);
      fd.append('title', title);
      fd.append('length', length);
      fd.append('engine', engine);
      if (text) fd.append('text', text); if (url) fd.append('url', url);
      for (const f of form.files.files){ fd.append('files', f); }
      fd.append('fetch_engine', form.fetch_engine.value);
      if (form.headful.checked) fd.append('headful','1'); if (form.persist_session.checked) fd.append('persist_session','1');
      if (form.referer.value) fd.append('referer', form.referer.value); if (form.timeout.value) fd.append('timeout', form.timeout.value);
      if (engine === 'llm'){
        const promptField = form.llm_prompt;
        if (promptField && promptField.value.trim()){
          fd.append('llm_prompt', promptField.value);
        }
      }
      setBusy(true);
      try{
        const res = await fetch('/summarize', { method: 'POST', body: fd });
        const data = await res.json();
        if(!res.ok){ showError(data.detail || '生成失败', data.trace || data.error || ''); return; }
        showResult(data);
      }catch(err){ showError(err.message || String(err)); }
      finally{ setBusy(false); }
    }
    function setBusy(b){ document.getElementById('btn').disabled = b; document.getElementById('status').textContent = b ? '正在生成与发布…' : ''; }
    function showError(msg, trace){ const el = document.getElementById('status'); el.textContent = msg; el.className='bad'; const pre = document.getElementById('trace'); if (pre){ if (trace){ pre.style.display='block'; pre.textContent = String(trace);} else { pre.style.display='none'; pre.textContent=''; } } const resBox = document.getElementById('result'); if (resBox){ resBox.style.display='block'; } const viewA = document.getElementById('view'); const downA = document.getElementById('download'); if (viewA){ viewA.href = '#'; viewA.textContent = '无可用链接（生成失败）'; } if (downA){ downA.href = '#'; } const frame = document.getElementById('frame'); if (frame){ const safe = (s)=> String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); const html = `<!doctype html><html><head><meta charset="utf-8"><style>body{font-family:system-ui,Segoe UI,Arial;padding:16px;color:#111}.bad{color:#b91c1c}pre{white-space:pre-wrap;background:#f8fafc;border:1px solid #e5e7eb;padding:12px;border-radius:8px}</style><title>Error</title></head><body><h2 class="bad">生成失败</h2><p>${safe(msg)}</p>${trace?`<pre>${safe(trace)}</pre>`:''}</body></html>`; frame.srcdoc = html; } resetSaveState(); }
    function showResult(data){ const s = document.getElementById('status'); if (data && data.warning){ s.textContent='生成成功（已回退）'; s.className='warn'; } else { s.textContent='生成成功'; s.className='good'; } const errBox = document.getElementById('errorbox'); if (errBox){ errBox.style.display='none'; } const v = location.origin + data.view_url; document.getElementById('view').href = v; document.getElementById('download').href = location.origin + data.download_url; document.getElementById('view').textContent = v; document.getElementById('frame').src = data.view_url; document.getElementById('result').style.display='block'; lastSummaryPayload = Object.assign({}, data, { view_url_absolute: v }); summaryFormSnapshot = captureFormSnapshot(); updateSaveButton(true); }
    function copyLink(){ const link = document.getElementById('view').href; navigator.clipboard.writeText(link).then(()=>{ const s = document.getElementById('status'); s.textContent='链接已复制'; s.className='good'; }).catch(()=>{}); }
  </script>
</head>
<body onload="initTheme();initForm()">
  <div class="topbar"><div class="inner"><div class="brand"><div class="logo"></div><div>HtmlSummary</div></div><div class="pill"><span class="muted">主题</span><button id="themeSwitch" class="switch" type="button" onclick="toggleTheme()"></button></div></div></div>
  <div class="wrap">
    <h1>HtmlSummary · 生成与发布摘要</h1>
    <div class="grid">
      <form id="f" class="card" onsubmit="submitForm(event)" enctype="multipart/form-data"> 
        <label>标题</label>
        <input type="text" name="title" placeholder="内容摘要" />
        <label>输入文本</label>
        <textarea name="text" placeholder="在此粘贴需要摘要的文本或 HTML/Markdown…"></textarea>
        <label>URL（可多条，逗号或换行分隔）</label>
        <textarea name="url" placeholder="https://example.com/article
https://mp.weixin.qq.com/xxx"></textarea>
        <div class="row">
          <label>URL获取方式</label>
          <select name="fetch_engine">
            <option value="requests" selected>直连（requests）</option>
            <option value="browser">浏览器渲染（Playwright）</option>
            <option value="selenium">浏览器渲染（Selenium + Chrome）</option>
          </select>
          <label style="margin-left:8px"><input type="checkbox" name="headful" value="1" /> 可视化浏览器（便于手动验证）</label>
          <label style="margin-left:8px"><input type="checkbox" name="persist_session" value="1" /> 记住会话（下次自动跳过验证）</label>
        </div>
        <div class="row">
          <label>Referer</label>
          <input type="text" name="referer" placeholder="可选，某些站点需要" style="flex:1" />
          <label style="margin-left:8px">超时(秒)</label>
          <input type="number" name="timeout" value="12" min="5" max="60" style="width:100px" />
        </div>
        <label>上传文件（.txt/.md/.html/.pdf/图片）</label>
        <input type="file" name="files" multiple accept=".txt,.md,.html,.htm,.pdf,image/*" />
        <label>输出格式</label>
        <div class="formats">
          <label><input type="radio" name="format_choice" value="text" checked /> 文本</label>
          <label><input type="radio" name="format_choice" value="cards" /> 卡片</label>
          <label><input type="radio" name="format_choice" value="flow" /> 流程图</label>
          <label><input type="radio" name="format_choice" value="table" /> 表格</label>
        </div>
        <div class="row"> 
          <label>引擎</label>
          <select name="engine"> 
            <option value="heuristic" selected>本地轻量（无需外网）</option>
            <option value="llm">大模型（LLM）</option>
          </select>
          <label>长度</label>
          <input type="number" name="length" min="1" max="15" value="5" style="width:110px" />
        </div>
        <div id="llmPromptBlock" style="display:none">
          <label>自定义提示词（LLM）</label>
          <textarea name="llm_prompt" id="llm_prompt" placeholder="可根据需要调整提示词，支持 {title} 与 {input_text} 占位符。"></textarea>
          <div class="hint">提示：仅在选择“大模型”时生效，可使用 {title} 和 {input_text} 占位符。</div>
        </div>
        <div class="row" style="margin-top:8px"> 
          <button id="btn" class="btn" type="submit">生成并发布</button>
          <span id="status" class="muted"></span>
          <pre id="trace" class="hint" style="display:none;white-space:pre-wrap"></pre>
        </div>
        <div class="hint">提示：图片与扫描 PDF 需要本机安装 Tesseract 才能 OCR。</div>
      </form>
      <div class="card">
        <h2 style="margin-top:0">预览与发布链接</h2>
        <div id="errorbox" style="display:none"><div class="bad" id="errmsg">出错了</div><pre id="errtrace" class="hint" style="white-space:pre-wrap"></pre></div>
        <div id="result" style="display:none"> 
          <div class="links"> 
            <a id="view" href="#" target="_blank">打开公共链接</a>
            <a id="download" href="#">下载 HTML</a>
            <button id="saveSummary" class="btn" onclick="saveSummary()" type="button" disabled>保存摘要</button>
            <button class="btn secondary" onclick="copyLink()" type="button">复制链接</button>
          </div>
          <div class="preview"> 
            <iframe id="frame" src="about:blank"></iframe>
          </div>
        </div>
        <div class="muted">生成后将在此展示预览与链接。</div>
      </div>
    </div>
  </div>
</body>
</html>
    """
    summary_service_url_json = json.dumps(SUMMARY_SERVICE_URL, ensure_ascii=False)
    html = html.replace("__PROMPTS_PLACEHOLDER__", prompts_json)
    html = html.replace("__SUMMARY_SERVICE_URL__", summary_service_url_json)
    return HTMLResponse(content=html)


@app.post("/summarize")
async def summarize(
    text: Optional[str] = Form(None),
    formats: Optional[str] = Form(None),
    format: Optional[str] = Form("text"),
    title: Optional[str] = Form("内容摘要"),
    length: Optional[int] = Form(5),
    url: Optional[str] = Form(None),
    engine: Optional[str] = Form("heuristic"),
    fetch_engine: Optional[str] = Form("requests"),
    headful: Optional[int] = Form(0),
    persist_session: Optional[int] = Form(0),
    referer: Optional[str] = Form(None),
    timeout: Optional[int] = Form(None),
    headers: Optional[str] = Form(None),
    llm_prompt: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = None,
):
    try:
        logger.info(
            f"/summarize start engine={engine} fetch_engine={fetch_engine} has_text={bool(text)} has_files={bool(files)} url_len={len((url or '').strip())} formats={formats} format={format} headful={headful} persist={persist_session} referer={referer} timeout={timeout}"
        )
    except Exception:
        pass

    texts: List[str] = []
    if text:
        texts.append(text)
    if url:
        raw = (url or "").replace("\r", "\n")
        parts = [p.strip() for p in raw.replace(",", "\n").split("\n") if p.strip()]
        extra_headers = None
        if headers:
            try:
                import json as _json
                extra_headers = _json.loads(headers)
                if not isinstance(extra_headers, dict):
                    extra_headers = None
            except Exception:
                extra_headers = None
        for u in parts:
            try:
                choice = (fetch_engine or "requests").lower()
                if choice == "browser":
                    _title, t = await fetch_text_via_playwright(u, headless=False if (headful or 0) else None, persist_session=bool(persist_session))
                elif choice == "selenium":
                    _title, t = fetch_text_via_selenium(u, headless=False if (headful or 0) else True, persist_session=bool(persist_session))
                else:
                    t = fetch_text_from_url(u, timeout=timeout or 12, referer=referer, extra_headers=extra_headers)
                texts.append(t)
            except BrowserFetchError as e:
                logger.error(f"Browser fetch failed url={u} engine_choice={choice}: {e}")
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                logger.exception(f"URL fetch failed url={u} engine_choice={choice}")
                raise HTTPException(status_code=400, detail=str(e))

    if files:
        for f in files:
            try:
                data = await f.read()
                t = load_text_from_upload(f.filename, data)
                texts.append(t)
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

    if not texts:
        raise HTTPException(status_code=400, detail="No input text or files provided")

    merged = merge_texts(texts)
    fmt_candidates: List[str] = []
    if format:
        fmt_candidates.append(format)
    if formats:
        fmt_candidates.extend([x for x in (formats or "").split(",") if x.strip()])
    fmt_list: List[str] = []
    for token in fmt_candidates:
        key = (token or "").strip().lower()
        if key and key not in fmt_list:
            fmt_list.append(key)
    if not fmt_list:
        fmt_list = ["text"]
    fmt_choice = fmt_list[0]
    if len(fmt_list) > 1:
        try:
            logger.warning(f"Multiple formats requested; falling back to first: {fmt_choice}")
        except Exception:
            pass

    engine_used = (engine or "heuristic").lower()
    if engine_used == "llm":
        fmt_for_llm = "flow" if fmt_choice in ("flow", "flowchart") else fmt_choice
        if fmt_for_llm not in ("text", "cards", "flow", "table"):
            raise HTTPException(status_code=400, detail=f"Unsupported format '{fmt_choice}' for LLM generation")
        prompt_override = (llm_prompt or "").strip() if llm_prompt else ""
        try:
            html = generate_html_with_llm(
                input_text=merged,
                title=title or "内容摘要",
                fmt=fmt_for_llm,
                prompt_override=prompt_override or None,
            )
        except Exception as e:
            msg = f"LLM generation failed: {e}"
            logger.exception(msg)
            if DEBUG_ERRORS:
                return JSONResponse(status_code=400, content={"detail": msg, "trace": traceback.format_exc()})
            raise HTTPException(status_code=400, detail=msg)
    else:
        outputs = {}
        fmt_key = fmt_choice
        if fmt_key == "text":
            outputs["text"] = render_text_summary(merged, length=length or 5)
        elif fmt_key == "cards":
            outputs["cards"] = render_cards_summary(merged, length=length or 5)
        elif fmt_key in ("flow", "flowchart"):
            outputs["flowchart"] = render_mermaid_flowchart(merged, length=(length or 5) + 1)
        elif fmt_key == "table":
            outputs["table"] = render_table_summary(merged, length=(length or 5))
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format '{fmt_choice}' for heuristic engine")
        html = build_html_document(title or "内容摘要", merged, outputs)

    result_id = str(uuid.uuid4())
    out_path = os.path.join(PUBLIC_DIR, f"{result_id}.html")
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(html)
    try:
        logger.info(f"/summarize done id={result_id} engine_used={engine_used} view_url=/public/{result_id}")
    except Exception:
        pass

    return JSONResponse({
        "result_id": result_id,
        "view_url": f"/public/{result_id}",
        "download_url": f"/public/{result_id}?download=1",
        "engine_used": engine_used,
    })


@app.post("/generate")
async def generate_api(payload: dict):
    input_content = (payload or {}).get("input_content")
    fmt = (payload or {}).get("format", "text")
    title = (payload or {}).get("title", "内容摘要")
    prompt_override = (payload or {}).get("prompt") or (payload or {}).get("llm_prompt")
    if not input_content or not isinstance(input_content, str):
        raise HTTPException(status_code=400, detail="input_content must be a non-empty string")
    fmt_norm = fmt.strip().lower()
    if fmt_norm == "card":
        fmt_norm = "cards"
    if fmt_norm not in ("text", "cards", "flow", "table"):
        raise HTTPException(status_code=400, detail="format must be one of: text|card|flow|table")
    try:
        prompt_text = (prompt_override.strip() if isinstance(prompt_override, str) else "") or None
        html = generate_html_with_llm(
            input_text=input_content,
            title=title,
            fmt=fmt_norm,
            prompt_override=prompt_text,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result_id = str(uuid.uuid4())
    out_path = os.path.join(PUBLIC_DIR, f"{result_id}.html")
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(html)

    return JSONResponse({
        "result_id": result_id,
        "view_url": f"/public/{result_id}",
        "download_url": f"/public/{result_id}?download=1",
    })


@app.get("/public/{result_id}")
def get_public(result_id: str, download: Optional[int] = None):
    path = os.path.join(PUBLIC_DIR, f"{result_id}.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    with open(path, "r", encoding="utf-8") as fp:
        html = fp.read()
    headers = {}
    if download:
        headers["Content-Disposition"] = f"attachment; filename=summary-{result_id}.html"
    return HTMLResponse(content=html, headers=headers)
