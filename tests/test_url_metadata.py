"""Unit tests for src/url_metadata.py."""

from src.url_metadata import (
    extract_metadata_from_html,
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
