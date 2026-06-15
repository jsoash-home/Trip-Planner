"""Unit tests for src/url_metadata.py."""

import logging
from types import SimpleNamespace

import requests

from src.url_metadata import (
    FETCH_USER_AGENT,
    extract_metadata_from_html,
    fetch_url_metadata,
    looks_like_url,
)


# ─────────────────────────────  looks_like_url  ────────────────────────────


def test_looks_like_url_http():
    assert looks_like_url("http://example.com") is True


def test_looks_like_url_https():
    assert looks_like_url("https://example.com/foo?bar=1") is True


def test_looks_like_url_with_surrounding_whitespace():
    assert looks_like_url("  https://example.com  ") is True


def test_looks_like_url_rejects_plain_text():
    assert looks_like_url("buy travel backpacks") is False


def test_looks_like_url_rejects_mailto():
    assert looks_like_url("mailto:foo@bar.com") is False


def test_looks_like_url_rejects_text_containing_url():
    # The rule is intentionally strict: only-URL is True, URL with any
    # prefix text is False. Keeps the form-handler logic simple.
    assert looks_like_url("check this http://example.com") is False


# ─────────────────────────  extract_metadata_from_html  ────────────────────


def test_extract_metadata_prefers_og_title():
    html = """
    <html><head>
        <meta property="og:title" content="OG Title Wins">
        <meta name="twitter:title" content="Twitter Title Loses">
        <title>Tag Title Loses</title>
    </head><body></body></html>
    """
    result = extract_metadata_from_html(html, "https://example.com/page")
    assert result["title"] == "OG Title Wins"


def test_extract_metadata_falls_back_to_twitter_title():
    html = """
    <html><head>
        <meta name="twitter:title" content="Twitter Title Wins">
        <title>Tag Title Loses</title>
    </head><body></body></html>
    """
    result = extract_metadata_from_html(html, "https://example.com/page")
    assert result["title"] == "Twitter Title Wins"


def test_extract_metadata_falls_back_to_title_tag():
    html = """
    <html><head>
        <title>Tag Title Wins</title>
    </head><body></body></html>
    """
    result = extract_metadata_from_html(html, "https://example.com/page")
    assert result["title"] == "Tag Title Wins"


def test_extract_metadata_falls_back_to_source_url():
    html = "<html><head></head><body>no metadata here</body></html>"
    source = "https://example.com/lonely-page"
    result = extract_metadata_from_html(html, source)
    assert result["title"] == source


def test_extract_metadata_prefers_og_image():
    html = """
    <html><head>
        <meta property="og:image" content="https://cdn.example.com/og.jpg">
        <meta name="twitter:image" content="https://cdn.example.com/twitter.jpg">
    </head></html>
    """
    result = extract_metadata_from_html(html, "https://example.com/page")
    assert result["image_url"] == "https://cdn.example.com/og.jpg"


def test_extract_metadata_no_image_returns_none():
    html = """
    <html><head>
        <title>No image here</title>
    </head></html>
    """
    result = extract_metadata_from_html(html, "https://example.com/page")
    assert result["image_url"] is None


def test_extract_metadata_resolves_relative_image_url():
    html = """
    <html><head>
        <meta property="og:image" content="/img/foo.jpg">
    </head></html>
    """
    result = extract_metadata_from_html(html, "https://example.com/page")
    assert result["image_url"] == "https://example.com/img/foo.jpg"


def test_extract_metadata_truncates_long_title():
    long_title = "x" * 300
    html = f"<html><head><title>{long_title}</title></head></html>"
    result = extract_metadata_from_html(html, "https://example.com/page")
    # 197 chars + "…" = 198 displayed chars
    assert len(result["title"]) == 198
    assert result["title"].endswith("…")


def test_extract_metadata_strips_title_whitespace():
    html = """
    <html><head>
        <title>   Padded Title   </title>
    </head></html>
    """
    result = extract_metadata_from_html(html, "https://example.com/page")
    assert result["title"] == "Padded Title"


# ────────────────────────────  fetch_url_metadata  ─────────────────────────


def test_fetch_url_metadata_success_returns_title_and_image(monkeypatch):
    fake_resp = SimpleNamespace(
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        text=(
            '<html><head>'
            '<meta property="og:title" content="Hello">'
            '<meta property="og:image" content="/img.jpg">'
            "</head></html>"
        ),
    )
    monkeypatch.setattr("src.url_metadata.requests.get", lambda *a, **k: fake_resp)
    result = fetch_url_metadata("https://example.com/page")
    assert result["title"] == "Hello"
    assert result["image_url"] == "https://example.com/img.jpg"
    assert result["source_url"] == "https://example.com/page"


def test_fetch_url_metadata_timeout_falls_back_to_url(monkeypatch, caplog):
    def boom(*a, **k):
        raise requests.exceptions.Timeout("timed out")

    monkeypatch.setattr("src.url_metadata.requests.get", boom)
    with caplog.at_level(logging.WARNING, logger="src.url_metadata"):
        result = fetch_url_metadata("https://slow.example.com")
    assert result == {
        "title": "https://slow.example.com",
        "image_url": None,
        "source_url": "https://slow.example.com",
    }
    assert any("failed" in rec.message for rec in caplog.records)


def test_fetch_url_metadata_http_404_falls_back_to_url(monkeypatch, caplog):
    fake_resp = SimpleNamespace(
        status_code=404,
        headers={"content-type": "text/html"},
        text="<html><head><title>Not Found</title></head></html>",
    )
    monkeypatch.setattr("src.url_metadata.requests.get", lambda *a, **k: fake_resp)
    with caplog.at_level(logging.WARNING, logger="src.url_metadata"):
        result = fetch_url_metadata("https://example.com/missing")
    assert result == {
        "title": "https://example.com/missing",
        "image_url": None,
        "source_url": "https://example.com/missing",
    }
    assert any("HTTP 404" in rec.message for rec in caplog.records)


def test_fetch_url_metadata_http_500_falls_back_to_url(monkeypatch, caplog):
    fake_resp = SimpleNamespace(
        status_code=500,
        headers={"content-type": "text/html"},
        text="<html><head><title>Server Error</title></head></html>",
    )
    monkeypatch.setattr("src.url_metadata.requests.get", lambda *a, **k: fake_resp)
    with caplog.at_level(logging.WARNING, logger="src.url_metadata"):
        result = fetch_url_metadata("https://example.com/boom")
    assert result == {
        "title": "https://example.com/boom",
        "image_url": None,
        "source_url": "https://example.com/boom",
    }
    assert any("HTTP 500" in rec.message for rec in caplog.records)


def test_fetch_url_metadata_non_html_content_type_falls_back_to_url(monkeypatch, caplog):
    fake_resp = SimpleNamespace(
        status_code=200,
        headers={"content-type": "application/pdf"},
        text="%PDF-1.4 ...",
    )
    monkeypatch.setattr("src.url_metadata.requests.get", lambda *a, **k: fake_resp)
    with caplog.at_level(logging.WARNING, logger="src.url_metadata"):
        result = fetch_url_metadata("https://example.com/doc.pdf")
    assert result == {
        "title": "https://example.com/doc.pdf",
        "image_url": None,
        "source_url": "https://example.com/doc.pdf",
    }
    assert any("non-HTML" in rec.message for rec in caplog.records)


def test_fetch_url_metadata_malformed_html_falls_back_to_url(monkeypatch, caplog):
    fake_resp = SimpleNamespace(
        status_code=200,
        headers={"content-type": "text/html"},
        text="<html><head><title>ok</title></head></html>",
    )
    monkeypatch.setattr("src.url_metadata.requests.get", lambda *a, **k: fake_resp)

    def explode(*a, **k):
        raise ValueError("parse boom")

    monkeypatch.setattr("src.url_metadata.extract_metadata_from_html", explode)
    with caplog.at_level(logging.WARNING, logger="src.url_metadata"):
        result = fetch_url_metadata("https://example.com/broken")
    assert result == {
        "title": "https://example.com/broken",
        "image_url": None,
        "source_url": "https://example.com/broken",
    }
    assert any("failed" in rec.message for rec in caplog.records)


def test_fetch_url_metadata_passes_timeout_and_user_agent_to_requests(monkeypatch):
    captured = {}

    def capture(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            status_code=200,
            headers={"content-type": "text/html"},
            text="<html></html>",
        )

    monkeypatch.setattr("src.url_metadata.requests.get", capture)
    fetch_url_metadata("https://example.com", timeout=2.5)
    assert captured["args"] == ("https://example.com",)
    assert captured["kwargs"]["timeout"] == 2.5
    assert captured["kwargs"]["headers"]["User-Agent"] == FETCH_USER_AGENT
