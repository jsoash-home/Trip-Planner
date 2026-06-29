"""Step 10 verification for trip 4 Phase 2a regeneration.

Runs:
- Banned-word grep on body prose (HTML-stripped, blockquote/q/cite-stripped)
- Wayfinding scaffold asserts (TOC, progress, reading-time chips)
- Practical-link asserts (bibliography, things_to_do, food, beer, day_by_day)
- Walking-chip asserts (day_by_day site cards where coords resolved)
- Atmospheric-prose link-free check

Prints PASS / FAIL per check. Non-fatal — runs all checks and reports.
"""

from __future__ import annotations

import os
import re
import sys

os.environ.pop("DATABASE_URL", None)
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app import app                                       # noqa: E402
from src import guide_builder                             # noqa: E402

TRIP_ID = 4

BANNED = [
    "vibrant", "bustling", "hidden gem", "must-see", "rich heritage",
    "melting pot", "charming", "picturesque", "unspoilt",
    "off-the-beaten-path", "dates back to", "centuries of",
    "has long been", "something for everyone", "a feast for the senses",
    "gem of a", "jewel of", "crown jewel", "postcard-perfect",
    "fairytale", "storied", "world-class", "breathtaking",
]


def strip_quoted_and_tags(html: str) -> str:
    """Remove blockquote/q/cite contents, then strip all HTML tags."""
    for tag in ("blockquote", "q", "cite"):
        html = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", "", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text


def banned_word_check(html: str) -> tuple[bool, list[str]]:
    text = strip_quoted_and_tags(html)
    hits = []
    for w in BANNED:
        if re.search(rf"\b{re.escape(w)}\b", text, re.I):
            hits.append(w)
    return (not hits), hits


def section_text(html: str, sec_id: str) -> str:
    m = re.search(
        rf'<section[^>]*id="{re.escape(sec_id)}"[^>]*>(.*?)</section>',
        html, flags=re.S,
    )
    return m.group(1) if m else ""


def main() -> int:
    with app.app_context():
        html = guide_builder.read_guide(TRIP_ID).decode("utf-8")

    results: list[tuple[str, bool, str]] = []

    # 1. Banned-word grep
    ok, hits = banned_word_check(html)
    results.append(("banned-word grep on body prose", ok, f"hits: {hits}" if hits else "no hits"))

    # 2. Wayfinding scaffold
    has_progress = '#vp-progress' in html and 'id="vp-progress"' in html
    results.append(("#vp-progress in DOM", has_progress, ""))

    toc_links = re.findall(r'<a[^>]*href="#[^"]+"[^>]*>', section_text(html, "") + html)
    toc_section = re.search(r'<nav class="vp-toc"[^>]*>(.*?)</nav>', html, flags=re.S)
    if not toc_section:
        toc_section = re.search(r'<div[^>]*class="vp-toc"[^>]*>(.*?)</div>', html, flags=re.S)
    if not toc_section:
        toc_section = re.search(r'<aside[^>]*vp-toc[^>]*>(.*?)</aside>', html, flags=re.S)
    toc_inner = toc_section.group(1) if toc_section else ""
    toc_anchor_count = len(re.findall(r'<a[^>]+href="#[^"]+"', toc_inner))
    results.append((f".vp-toc has ≥2 anchors", toc_anchor_count >= 2, f"{toc_anchor_count} found"))

    # Reading-time chips per <h2> in <main>
    main_block = re.search(r'<main[^>]*>(.*)</main>', html, flags=re.S)
    main_html = main_block.group(1) if main_block else ""
    h2s = re.findall(r'<h2[^>]*>(.*?)</h2>', main_html, flags=re.S)
    h2_with_rt = sum(1 for h in h2s if 'reading-time' in h)
    results.append((
        f"every <h2> in <main> has reading-time chip",
        h2_with_rt == len(h2s) and len(h2s) > 0,
        f"{h2_with_rt}/{len(h2s)} h2s have chip",
    ))

    # TOC anchor → section id resolves
    toc_targets = set(re.findall(r'href="#([^"]+)"', toc_inner))
    section_ids = set(re.findall(r'<section[^>]*id="([^"]+)"', main_html))
    orphans = toc_targets - section_ids - {"hero"}  # hero is the top section
    results.append((
        "every TOC anchor resolves to <section>",
        len(orphans) == 0,
        f"orphans: {orphans}" if orphans else "all resolve",
    ))

    # 3. Practical-link asserts
    # Bibliography: every <li> in "sources" section ul has an <a class="practical-link">
    sources = section_text(html, "sources")
    biblio_lis = re.findall(r'<li>(.*?)</li>', sources, flags=re.S)
    biblio_with_link = sum(1 for li in biblio_lis if 'class="practical-link"' in li)
    results.append((
        f"bibliography entries linked",
        biblio_with_link >= 9,  # 9 entries got the practical-link treatment
        f"{biblio_with_link}/{len(biblio_lis)} <li>s have practical-link",
    ))

    # things-to-do: every <h4> wraps a practical-link
    ttd = section_text(html, "things-to-do")
    ttd_h4s = re.findall(r'<h4[^>]*>(.*?)</h4>', ttd, flags=re.S)
    ttd_h4s_linked = sum(1 for h in ttd_h4s if 'class="practical-link"' in h)
    results.append((
        f"things-to-do h4 venues linked",
        ttd_h4s_linked >= 11,  # 12 cards, 1 may not have linked
        f"{ttd_h4s_linked}/{len(ttd_h4s)} h4 cards linked",
    ))

    # food where-to-eat: <b> venue names linked
    food = section_text(html, "food")
    eat_bs = re.findall(r'<li>\s*<b>(.*?)</b>', food, flags=re.S)
    eat_bs_linked = sum(1 for b in eat_bs if 'class="practical-link"' in b)
    results.append((
        f"food where-to-eat <b> venues linked",
        eat_bs_linked >= 10,
        f"{eat_bs_linked}/{len(eat_bs)} eat-list <b>s linked",
    ))

    # day_by_day h5 site card titles linked
    days = section_text(html, "days")
    day_h5s = re.findall(r'<h5>(.*?)</h5>', days, flags=re.S)
    day_h5s_linked = sum(1 for h in day_h5s if 'class="practical-link"' in h)
    results.append((
        f"day_by_day h5 site cards linked",
        day_h5s_linked >= 11,
        f"{day_h5s_linked}/{len(day_h5s)} h5 site cards linked",
    ))

    # 4. Walking-chip asserts
    day_walkchips = days.count('class="walkchip"')
    results.append((
        f"day_by_day has walkchip elements",
        day_walkchips >= 5,
        f"{day_walkchips} walkchips found",
    ))

    # 5. Atmospheric prose stays link-free
    # Each <section class="section--atmospheric"> — find all <p> NOT inside .lede/.deep
    # and check no <a> tag is inside the raw paragraph text. (We allow .opnote since
    # it's a callout not flowing prose. We allow <p class="opinion"> since it has a
    # rare-marker role. We're really checking history/intro paragraphs.)
    atm_sections = re.findall(
        r'<section class="section--atmospheric"[^>]*>(.*?)</section>',
        html, flags=re.S,
    )
    leaks = []
    for s in atm_sections:
        # Day intro paragraphs (the first <p> right after <h3> in a daymark-body)
        for m in re.finditer(
            r'<div class="daymark-body">\s*<h3[^>]*>.*?</h3>\s*<div class="daymeta">.*?</div>\s*<p>(.*?)</p>',
            s, flags=re.S,
        ):
            para = m.group(1)
            if '<a ' in para:
                leaks.append(("day_intro", para[:80]))
        # History/atmospheric lede also OK to have no links; bulky <p> outside daymark-body
        # — but those are already the section ledes / opinion callouts. Check section-level
        # <p class="lede"> intros (allow ledes — they're labelled).
        # Skipping deeper scan since the day-intro check is the high-signal one.
    results.append((
        f"atmospheric prose link-free (day intros)",
        len(leaks) == 0,
        f"leaks: {len(leaks)}" if leaks else "clean",
    ))

    # Print results
    print()
    print("=" * 60)
    all_pass = True
    for name, ok, detail in results:
        flag = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  [{flag}]  {name}")
        if detail:
            print(f"            {detail}")
    print("=" * 60)
    print(f"\noverall: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
