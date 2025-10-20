import os
import re
from typing import Literal

# Load .env if present
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


# Provider and defaults
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").lower()
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
LLM_MODEL = (
    os.getenv("LLM_MODEL")
    or (
        os.getenv("OPENAI_MODEL")
        if LLM_PROVIDER == "openai"
        else None
    )
    or ("deepseek-chat" if LLM_PROVIDER == "deepseek" else "gpt-4o-mini")
)
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or (
    "https://api.deepseek.com" if LLM_PROVIDER == "deepseek" else None
)


PROMPT_TEXT = (
    "生成一个 HTML 文件，内容是以下文本的总结。请严格按照要求输出完整 HTML：\n"
    "1. 标题放在 <h1> 标签中\n"
    "2. 要点列表使用 <ul> 和 <li> 标签展示\n"
    "3. 摘要内容放在段落 <p> 中，简洁清晰\n\n"
    "标题：{title}\n"
    "文本：{input_text}\n"
    "请先对文本进行简洁摘要，再生成符合要求的 HTML 页面。"
)

PROMPT_CARDS = (
    "生成一个 HTML 文件，内容是以下文本的总结，并以卡片形式展示每个要点。"
    "每个卡片包含一个小标题和简短描述，并使用合适的 CSS，让卡片之间有间距。\n\n"
    "标题：{title}\n"
    "文本：{input_text}\n"
    "请先对文本进行简洁摘要，提炼 4-8 条要点，再生成符合要求的 HTML 页面。"
)

PROMPT_FLOW = (
    "生成一个 HTML 文件，内容是以下文本的总结，并以流程图形式展示要点。"
    "请使用 Mermaid.js 语法生成一个包含关键步骤与流向的流程图。\n\n"
    "标题：{title}\n"
    "文本：{input_text}\n"
    "请先对文本进行简洁摘要，再基于摘要抽取关键步骤并生成 Mermaid 流程图，同时输出完整 HTML 页面（包含 <pre class=\"mermaid\"> 或引入 mermaid 以便渲染）。"
)

PROMPT_TABLE = (
    "生成一个 HTML 文件，内容是以下文本的总结，并以表格形式展示要点。"
    "表格的每一行包含一个标题和对应内容，表格整洁且列对齐。\n\n"
    "标题：{title}\n"
    "文本：{input_text}\n"
    "请先对文本进行简洁摘要，再生成表格形式的 HTML 页面。"
)


def _get_client():
    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        raise RuntimeError(
            "LLM client not available: Python package 'openai' is not installed. "
            "Install with: pip install openai"
        )

    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY (or OPENAI_API_KEY) is not set for LLM generation.")
    # Build an httpx client that honors system/environment proxies to avoid passing unsupported args
    http_client = None
    try:
        import httpx  # type: ignore
        # trust_env=True lets httpx read HTTP_PROXY/HTTPS_PROXY/NO_PROXY etc.
        http_client = httpx.Client(trust_env=True, timeout=60.0)
    except Exception:
        http_client = None

    try:
        if LLM_BASE_URL:
            return OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, http_client=http_client)
        return OpenAI(api_key=LLM_API_KEY, http_client=http_client)
    except TypeError as te:
        # Give a clearer message if the environment or wrapper passes unsupported kwargs like 'proxies'
        raise RuntimeError(
            f"Failed to initialize LLM client: {te}. If you are setting proxy via custom code or env, "
            f"avoid passing 'proxies' to OpenAI(); use standard HTTP(S)_PROXY envs or set trust_env via httpx."
        )


def generate_html_with_llm(
    *,
    input_text: str,
    title: str,
    fmt: Literal["text", "cards", "flow", "table"],
    model: str | None = None,
) -> str:
    client = _get_client()
    model = model or LLM_MODEL

    if fmt == "text":
        prompt = PROMPT_TEXT.format(title=title, input_text=input_text)
    elif fmt == "cards":
        prompt = PROMPT_CARDS.format(title=title, input_text=input_text)
    elif fmt == "flow":
        prompt = PROMPT_FLOW.format(title=title, input_text=input_text)
    elif fmt == "table":
        prompt = PROMPT_TABLE.format(title=title, input_text=input_text)
    else:
        raise ValueError("Unsupported format for LLM generation")

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一个擅长摘要与网页排版的助手，输出必须是有效的 HTML。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    content = resp.choices[0].message.content or ""
    return _normalize_llm_html(content.strip(), title)


def _normalize_llm_html(s: str, title: str) -> str:
    if not s:
        return s
    text = s.strip()
    # Strip Markdown code fences like ```html ... ``` or ``` ... ```
    m = re.fullmatch(r"```\s*html\s*\n([\s\S]*?)\n```\s*", text, flags=re.IGNORECASE)
    if m:
        text = m.group(1).strip()
    else:
        m2 = re.fullmatch(r"```\s*\n([\s\S]*?)\n```\s*", text)
        if m2:
            text = m2.group(1).strip()
    if text.startswith("```") and text.endswith("```") and len(text) > 6:
        inner = text[3:-3].strip()
        if inner.lower().startswith("html\n"):
            inner = inner[5:].strip()
        text = inner
    lower = text.lower()
    if ("<html" in lower) or ("<!doctype" in lower):
        return text
    if "<" in text and ">" in text:
        return (
            f"<!doctype html><html lang=\"zh-CN\"><head>"
            f"<meta charset=\"utf-8\"/><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>"
            f"<title>{title}</title></head><body>{text}</body></html>"
        )
    return text
