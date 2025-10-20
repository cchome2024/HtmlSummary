import math
import re
import uuid
from collections import Counter
from typing import Dict, List, Tuple


SENTENCE_SPLIT_PATTERN = re.compile(
    r"(?<=[。！？!?\.;:])\s+|\n+",
    flags=re.U,
)

WORD_SPLIT_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[\u4e00-\u9fff]", re.U)

STOPWORDS_EN = set(
    """
    a an the and or but if while is are was were be been being of in on for to from by with without as at into about over under again further then once here there all any both each few more most other some such no nor not only own same so than too very can will just should now
    """.split()
)

STOPWORDS_ZH = set("的 了 和 与 及 并 又 将 把 在 是 为 也 就 而 及 之 其 他们 我们 你们 以及 或者 如果 由于 因为 所以 并且 而且 不是 没有 非 常 更 更加 可能 可以 应该 需要 通过 对 于 来 去 与 及 这 那 这些 那些 一个 一些 任何 每个 各种".split())


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def split_sentences(text: str) -> List[str]:
    parts = re.split(SENTENCE_SPLIT_PATTERN, text)
    sents = [s.strip() for s in parts if s and s.strip()]
    # Merge very short fragments with next sentence to reduce noise
    merged: List[str] = []
    buf = ""
    for s in sents:
        if len(s) < 15:
            buf = (buf + " " + s).strip()
            continue
        if buf:
            merged.append((buf + " " + s).strip())
            buf = ""
        else:
            merged.append(s)
    if buf:
        merged.append(buf)
    return merged


def tokenize(text: str) -> List[str]:
    tokens = [m.group(0).lower() for m in WORD_SPLIT_PATTERN.finditer(text)]
    return tokens


def filter_tokens(tokens: List[str]) -> List[str]:
    if any("\u4e00" <= ch <= "\u9fff" for tok in tokens for ch in tok):
        return [t for t in tokens if t not in STOPWORDS_ZH]
    return [t for t in tokens if t not in STOPWORDS_EN]


def sentence_scores(sentences: List[str]) -> List[float]:
    # Frequency-based scoring, plus mild position and length bonuses
    all_tokens = []
    sent_tokens: List[List[str]] = []
    for s in sentences:
        toks = filter_tokens(tokenize(s))
        sent_tokens.append(toks)
        all_tokens.extend(toks)

    freq = Counter(all_tokens)
    if not freq:
        return [0.0 for _ in sentences]

    max_f = max(freq.values())
    scores = []
    n = len(sentences)
    for i, (s, toks) in enumerate(zip(sentences, sent_tokens)):
        base = sum(freq.get(t, 0) for t in toks) / (len(toks) + 1e-6)
        base = base / (max_f + 1e-6)
        # Position bonus: earlier sentences get a slight boost
        pos_bonus = 1.0 - (i / (n + 1.0)) * 0.15
        # Length bonus: prefer medium-length sentences
        L = len(s)
        len_bonus = 1.0
        if L < 40:
            len_bonus = 0.85
        elif L > 280:
            len_bonus = 0.9
        scores.append(base * pos_bonus * len_bonus)
    return scores


def top_k_sentences(text: str, k: int = 5) -> List[Tuple[int, str]]:
    sents = split_sentences(text)
    if not sents:
        return []
    k = max(1, min(k, len(sents)))
    scores = sentence_scores(sents)
    ranked_idx = sorted(range(len(sents)), key=lambda i: scores[i], reverse=True)[:k]
    # Keep original order for readability
    ranked_idx.sort()
    return [(i, sents[i]) for i in ranked_idx]


def extract_keywords(text: str, topn: int = 6) -> List[str]:
    tokens = filter_tokens(tokenize(text))
    freq = Counter(tokens)
    if not freq:
        return []
    # Prefer longer alphabetic tokens or frequent Chinese characters
    items = sorted(freq.items(), key=lambda kv: (kv[1], len(kv[0])), reverse=True)
    out: List[str] = []
    for t, _ in items:
        if t.isdigit():
            continue
        if len(t) <= 1:
            continue
        out.append(t)
        if len(out) >= topn:
            break
    return out


def render_text_summary(text: str, length: int = 5) -> str:
    picks = top_k_sentences(text, length)
    return "\n".join(s for _, s in picks)


def render_cards_summary(text: str, length: int = 5) -> List[str]:
    picks = top_k_sentences(text, length)
    return [s for _, s in picks]


def render_mermaid_flowchart(text: str, length: int = 6) -> str:
    picks = top_k_sentences(text, length)
    if not picks:
        return "graph TD; A[No content]"
    nodes = []
    edges = []
    for idx, (_, s) in enumerate(picks, start=1):
        nid = f"N{idx}"
        label = s.strip().replace("[", "(").replace("]", ")")
        label = label.replace("\n", " ")
        if len(label) > 60:
            label = label[:57] + "..."
        nodes.append(f"{nid}[{label}]")
        if idx > 1:
            edges.append(f"N{idx-1} --> {nid}")
    return "graph TD\n  " + "\n  ".join(nodes + edges)


def render_table_summary(text: str, length: int = 6) -> List[Tuple[str, str]]:
    # Produce pairs of (Key, Content) from top sentences and keywords
    sentences = [s for _, s in top_k_sentences(text, length)]
    kws = extract_keywords(text, topn=min(8, max(3, length)))
    rows: List[Tuple[str, str]] = []
    for i, s in enumerate(sentences, start=1):
        key = (kws[i - 1] if i - 1 < len(kws) else f"要点{i}") if kws else f"要点{i}"
        rows.append((key, s))
    return rows


def build_html_document(
    title: str,
    original: str,
    outputs: Dict[str, object],
) -> str:
    doc_id = str(uuid.uuid4())
    css = """
    body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,Helvetica,sans-serif;max-width:920px;margin:32px auto;padding:0 16px;color:#1f2937;}
    header{margin-bottom:16px}
    h1{font-size:28px;margin:0 0 4px}
    .meta{color:#6b7280;font-size:12px}
    section{margin:24px 0;padding:16px;border:1px solid #e5e7eb;border-radius:8px;background:#fff}
    h2{font-size:18px;margin:0 0 12px}
    pre{white-space:pre-wrap;word-wrap:break-word;background:#f8fafc;padding:12px;border-radius:6px}
    ul{margin:0;padding-left:18px}
    table{border-collapse:collapse;width:100%}
    th,td{border:1px solid #e5e7eb;padding:8px;text-align:left}
    .toolbar{display:flex;gap:8px;margin:8px 0}
    .pill{padding:4px 8px;border:1px solid #e5e7eb;border-radius:999px;color:#374151;background:#f9fafb}
    .mermaid{background:#f8fafc;padding:12px;border-radius:6px}
    """
    # Mermaid script is optional; render code block for portability.
    text_html = ""
    if "text" in outputs and outputs["text"]:
        text_html = f"<section><h2>文本总结</h2><pre>{escape_html(str(outputs['text']))}</pre></section>"
    cards_html = ""
    if "cards" in outputs and outputs["cards"]:
        items = outputs["cards"] or []
        cards_html = "<section><h2>卡片式总结</h2><ul>" + "".join(
            f"<li>{escape_html(it)}</li>" for it in items
        ) + "</ul></section>"
    flow_html = ""
    if "flowchart" in outputs and outputs["flowchart"]:
        code = escape_html(str(outputs["flowchart"]))
        flow_html = f"<section><h2>流程图总结（Mermaid）</h2><pre class=\"mermaid\">{code}</pre></section>"
    table_html = ""
    if "table" in outputs and outputs["table"]:
        rows = outputs["table"] or []
        tr = "".join(f"<tr><th>{escape_html(k)}</th><td>{escape_html(v)}</td></tr>" for k, v in rows)
        table_html = f"<section><h2>表格总结</h2><table><tbody>{tr}</tbody></table></section>"

    original_html = f"<section><h2>原文（片段）</h2><pre>{escape_html(original[:2000])}</pre></section>" if original else ""

    html = f"""
<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
  <title>{escape_html(title)}</title>
  <style>{css}</style>
  <meta name=\"generator\" content=\"HtmlSummary Service\" />
  <meta name=\"doc-id\" content=\"{doc_id}\" />
</head>
<body>
  <header>
    <h1>{escape_html(title)}</h1>
    <div class=\"meta\">Generated by HtmlSummary • ID {doc_id}</div>
    <div class=\"toolbar\">
      <span class=\"pill\">文本</span>
      <span class=\"pill\">卡片</span>
      <span class=\"pill\">流程图</span>
      <span class=\"pill\">表格</span>
    </div>
  </header>
  {text_html}
  {cards_html}
  {flow_html}
  {table_html}
  {original_html}
</body>
</html>
"""
    return html


def escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )

