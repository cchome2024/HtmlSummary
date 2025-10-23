import json
import os
import re
import time
from typing import Any, Literal

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

DEFAULT_PROMPTS = {
    "text": PROMPT_TEXT,
    "cards": PROMPT_CARDS,
    "flow": PROMPT_FLOW,
    "table": PROMPT_TABLE,
}


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


def _render_prompt_template(template: str, title: str, input_text: str) -> str:
    try:
        return template.format(title=title, input_text=input_text)
    except Exception:
        return (
            template.replace("{title}", title)
            .replace("{input_text}", input_text)
        )


def generate_html_with_llm(
    *,
    input_text: str,
    title: str,
    fmt: Literal["text", "cards", "flow", "table"],
    model: str | None = None,
    prompt_override: str | None = None,
) -> str:
    client = _get_client()
    model = model or LLM_MODEL

    template = DEFAULT_PROMPTS.get(fmt)
    if not template:
        raise ValueError("Unsupported format for LLM generation")
    override = (prompt_override or "").strip()
    prompt_template = override or template
    prompt = _render_prompt_template(prompt_template, title, input_text)

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
    if "</html>" in lower:
        end = lower.rfind("</html>") + len("</html>")
        text = text[:end]
        lower = text.lower()
    if text.startswith("```html"):
        text = text[len("```html"):].lstrip("\r\n")
        lower = text.lower()
    elif text.startswith("```"):
        text = text[len("```"):].lstrip("\r\n")
        lower = text.lower()
    if ("<html" in lower) or ("<!doctype" in lower):
        return text
    if "<" in text and ">" in text:
        return (
            f"<!doctype html><html lang=\"zh-CN\"><head>"
            "<meta charset=\"utf-8\"/><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>"
            f"<title>{title}</title></head><body>{text}</body></html>"
        )
    return text


def call_mcp_save_via_llm(
    *,
    arguments: dict[str, Any],
    mcp_base_url: str,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Use function-calling to ask the LLM which arguments to send to the MCP save_summary tool,
    execute the tool call, and return the MCP result.
    """
    client = _get_client()
    model = model or LLM_MODEL

    save_summary_schema = {
        "type": "object",
        "properties": {
            "user_input": {"type": "string", "description": "原始输入文本，可为空"},
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
                "description": "完整 HTML 内容，必须提供",
            },
            "title": {"type": "string", "description": "摘要标题，可选"},
            "source_view_url": {"type": "string", "description": "原始预览地址，可选"},
            "result_id": {"type": "string", "description": "前端生成的摘要 ID，可选"},
        },
        "required": ["html_content"],
        "additionalProperties": False,
    }

    user_message = (
        "请基于提供的摘要数据调用 `save_summary` 工具，确保 HTML 内容原样传递。"
        "如无额外补充，不要改动字段，仅按 JSON schema 输出参数。"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是一个负责调用保存摘要工具的助手。只允许通过工具返回结果，不要输出额外文本。",
            },
            {"role": "user", "content": user_message},
            {"role": "user", "content": json.dumps(arguments, ensure_ascii=False)},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "save_summary",
                    "description": "保存摘要 HTML 内容到 MCP 服务",
                    "parameters": save_summary_schema,
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": "save_summary"}},
        temperature=0,
    )

    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None) or []
    if not tool_calls:
        raise RuntimeError("LLM 未返回保存摘要的工具调用结果")
    tool_call = tool_calls[0]
    try:
        tool_arguments = json.loads(tool_call.function.arguments or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"解析 LLM 工具参数失败: {exc}") from exc

    # 后备：如果 LLM 未携带关键字段，补上原始 arguments
    if "html_content" not in tool_arguments:
        tool_arguments["html_content"] = arguments.get("html_content", "")
    if "urls" not in tool_arguments:
        tool_arguments["urls"] = arguments.get("urls", [])
    if "filenames" not in tool_arguments:
        tool_arguments["filenames"] = arguments.get("filenames", [])
    if "user_input" not in tool_arguments:
        tool_arguments["user_input"] = arguments.get("user_input", "")
    for key in ("title", "source_view_url", "result_id"):
        if key not in tool_arguments and key in arguments:
            tool_arguments[key] = arguments[key]

    rpc_payload = {
        "jsonrpc": "2.0",
        "id": int(time.time() * 1000),
        "method": "call_tool",
        "params": {
            "name": "save_summary",
            "arguments": tool_arguments,
        },
    }

    try:
        import httpx  # type: ignore
    except ImportError as exc:
        raise RuntimeError("请安装 httpx 以调用 MCP 服务：pip install httpx") from exc

    with httpx.Client(trust_env=True, timeout=60.0) as client_http:
        response = client_http.post(
            f"{mcp_base_url.rstrip('/')}/mcp",
            json=rpc_payload,
        )
        response.raise_for_status()
        payload = response.json()

    if isinstance(payload, dict) and payload.get("error"):
        message = payload["error"].get("message") if isinstance(payload["error"], dict) else str(payload["error"])
        raise RuntimeError(message or "MCP 返回错误")

    if not isinstance(payload, dict) or "result" not in payload:
        raise RuntimeError("MCP 响应不合法")

    return payload["result"]
