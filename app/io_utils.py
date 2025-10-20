import os
import re
import logging
from typing import List, Optional, Dict


ALLOWED_EXTS = {
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tif",
    ".tiff",
    ".webp",
}


def ensure_public_dir(base: str) -> str:
    public_dir = os.path.join(base, "public")
    os.makedirs(public_dir, exist_ok=True)
    return public_dir


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name)
    return name[:100] or "file"


def detect_html(text: str) -> bool:
    snippet = text.strip()[:200].lower()
    return "<html" in snippet or "<p" in snippet or "<div" in snippet


def strip_html(text: str) -> str:
    # Minimal HTML tag stripper using regex; safe for simple HTML.
    # Not suitable for malformed HTML; replace with robust parser if needed.
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\t+", " ", text)
    text = re.sub(r"\s+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_encoding_from_meta(html_bytes: bytes) -> Optional[str]:
    try:
        head = html_bytes[:2048].decode('ascii', errors='ignore').lower()
    except Exception:
        return None
    m = re.search(r"<meta[^>]+charset=['\"]?([a-z0-9_-]+)", head)
    if m:
        return m.group(1).strip()
    m2 = re.search(r"<\?xml[^>]+encoding=['\"]?([a-z0-9_-]+)", head)
    if m2:
        return m2.group(1).strip()
    return None


def smart_decode(data: bytes, headers: Optional[Dict[str, str]] = None) -> str:
    charset = None
    if headers:
        ctype = (headers.get('Content-Type') or '').lower()
        m = re.search(r"charset=([a-z0-9_-]+)", ctype)
        if m:
            charset = m.group(1).strip()
    if not charset:
        meta_cs = _detect_encoding_from_meta(data)
        if meta_cs:
            charset = meta_cs
    if charset:
        try:
            return data.decode(charset, errors='replace')
        except Exception:
            pass
    try:
        from charset_normalizer import from_bytes  # type: ignore
        best = from_bytes(data).best()
        if best and best.encoding:
            return str(best)
    except Exception:
        pass
    return data.decode('utf-8', errors='replace')


def load_text_from_upload(filename: str, data: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise ValueError(f"Unsupported file type: {ext}")
    if ext in {".html", ".htm", ".txt", ".md"}:
        text = smart_decode(data)
        if ext in {".html", ".htm"} or detect_html(text):
            text = strip_html(text)
        return normalize_text(text)
    if ext == ".pdf":
        return normalize_text(load_text_from_pdf_bytes(data))
    if ext in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
        return normalize_text(load_text_from_image_bytes(data))
    raise ValueError(f"Unsupported file type: {ext}")


def merge_texts(texts: List[str]) -> str:
    texts = [t.strip() for t in texts if t and t.strip()]
    return "\n\n".join(texts)


def load_text_from_pdf_bytes(data: bytes) -> str:
    from io import BytesIO
    from pypdf import PdfReader

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {e}")
    parts: List[str] = []
    for page in reader.pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt:
            parts.append(txt)
    text = "\n".join(parts)
    if not text.strip():
        # Some PDFs are image-based and require OCR
        raise ValueError("PDF contains no extractable text (possibly scanned). Consider OCR.")
    return text


def load_text_from_image_bytes(data: bytes) -> str:
    from io import BytesIO
    try:
        from PIL import Image
    except Exception as e:
        raise ValueError(f"Pillow not available for image processing: {e}")
    try:
        import pytesseract
        from pytesseract import TesseractNotFoundError
    except Exception as e:
        raise ValueError(f"pytesseract not available for OCR: {e}")

    try:
        img = Image.open(BytesIO(data))
    except Exception as e:
        raise ValueError(f"Invalid image: {e}")

    try:
        # Let Tesseract auto-detect language; users can tune via env or configs later
        text = pytesseract.image_to_string(img)
    except Exception as e:
        # Tesseract binary not found or OCR failed
        raise ValueError(f"OCR failed: {e}")
    return text or ""


logger = logging.getLogger("htmlsummary")


def fetch_text_from_url(
    url: str,
    timeout: int = 12,
    referer: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
    import requests

    # Use a realistic desktop UA; some sites block custom/unknown UAs
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if referer:
        headers["Referer"] = referer
    if extra_headers:
        try:
            for k, v in extra_headers.items():
                if isinstance(k, str) and isinstance(v, str):
                    headers[k] = v
        except Exception:
            pass
    try:
        logger.info(f"HTTP fetch start url={url} timeout={timeout} referer={referer} headers_keys={list(headers.keys())}")
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    except Exception as e:
        logger.exception(f"HTTP fetch exception url={url}: {e}")
        raise ValueError(f"Failed to fetch URL: {e}")
    if resp.status_code >= 400:
        logger.error(f"HTTP fetch bad status url={url} status={resp.status_code}")
        raise ValueError(f"Fetch failed with status {resp.status_code}")
    ctype = resp.headers.get("Content-Type", "").lower()
    logger.info(f"HTTP fetch ok url={url} status={resp.status_code} ctype={ctype}")
    text = smart_decode(resp.content, headers=resp.headers)
    if "html" in ctype or detect_html(text):
        text = strip_html(text)
    return normalize_text(text)
