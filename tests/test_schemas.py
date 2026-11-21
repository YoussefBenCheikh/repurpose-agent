import pytest
from pydantic import ValidationError

from repurpose_agent.ingest import extract_text, make_document
from repurpose_agent.schemas import Critique, PinterestPin, XThread


def pin(**kw):
    base = dict(
        title="t", description="d", hashtags=["a", "b", "c"], image_prompt="i", board_suggestion="b"
    )
    return PinterestPin(**(base | kw))


def test_hashtags_are_normalized_and_deduped():
    p = pin(hashtags=["#SaaS", "saas", " Dev Tips ", "#AI"])
    assert p.hashtags == ["saas", "devtips", "ai"]


def test_pin_title_limit():
    with pytest.raises(ValidationError, match="max is 100"):
        pin(title="x" * 101)


def test_too_few_hashtags_after_dedupe():
    with pytest.raises(ValidationError, match="3-5 unique"):
        pin(hashtags=["a", "#A", "b"])


def test_thread_post_length():
    with pytest.raises(ValidationError, match=r"posts \[2\]"):
        XThread(tweets=["ok", "x" * 281])


def test_critique_score_range():
    with pytest.raises(ValidationError):
        Critique(score=11, strengths=[], issues=[])


def test_extract_text_prefers_article_and_strips_nav():
    html = """<html><head><title>My Post</title></head><body>
      <nav><p>Menu junk</p></nav>
      <article><h1>Heading</h1><p>Real content.</p><script>x()</script></article>
    </body></html>"""
    title, text = extract_text(html)
    assert title == "My Post"
    assert "Real content." in text and "Menu junk" not in text and "x()" not in text


def test_make_document_flags_truncation():
    doc = make_document("t", "a" * 50, None, max_chars=10)
    assert doc.truncated and len(doc.text) == 10
