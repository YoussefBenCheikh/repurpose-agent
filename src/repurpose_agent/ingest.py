"""Fetch a URL and extract readable text."""

import logging

import httpx
from bs4 import BeautifulSoup

from repurpose_agent.schemas import SourceDocument

log = logging.getLogger(__name__)

_STRIP_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg"]


def extract_text(html: str) -> tuple[str, str]:
    """Return (title, body_text) from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""
    for tag in soup(_STRIP_TAGS):
        tag.decompose()

    root = soup.find("article") or soup.find("main") or soup.body or soup
    blocks = [
        el.get_text(" ", strip=True)
        for el in root.find_all(["h1", "h2", "h3", "p", "li", "blockquote"])
    ]
    text = "\n".join(b for b in blocks if b)
    if not title:
        h1 = root.find("h1")
        title = h1.get_text(strip=True) if h1 else "Untitled"
    return title, text


def make_document(title: str, text: str, url: str | None, max_chars: int) -> SourceDocument:
    truncated = len(text) > max_chars
    if truncated:
        log.warning("Source is %d chars; keeping the first %d.", len(text), max_chars)
        text = text[:max_chars]
    return SourceDocument(url=url, title=title, text=text, truncated=truncated)


def fetch_url(url: str, *, timeout: float, max_chars: int) -> SourceDocument:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; repurpose-agent/0.1)"}
    resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    title, text = extract_text(resp.text)
    if len(text) < 200:
        raise ValueError(f"Extracted only {len(text)} chars from {url}; page may need JS.")
    return make_document(title, text, url, max_chars)
