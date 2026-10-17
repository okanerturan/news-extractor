"""Body-text cleanup rules for Turkish news pages.

Everything publisher-specific lives in the data lists at the top of this
module, so supporting a new outlet's boilerplate is a one line change:

* ``INLINE_BOILERPLATE``: phrases removed wherever they occur.
* ``DROP_LINES``: whole paragraphs removed (pattern, maximum length).
* ``LEADING_LINES``: byline and timestamp lines removed from the start only.
* ``RELATED_HEADINGS``: a heading that ends the article body.
* ``TRAILING_LINES``: teaser-like lines removed from the end only.
* ``IGNORED_ATTRIBUTE_WORDS``: class/id words that mark non-content containers.
* ``GENERIC_KEYWORDS`` / ``NAV_KEYWORDS``: site-wide keyword boilerplate.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping

_APOS = r"[’'`´]?"
_MONTHS = (
    r"(?:Ocak|Şubat|Mart|Nisan|Mayıs|Haziran|Temmuz|Ağustos|Eylül|Ekim|Kasım|Aralık)"
)

# Phrases removed wherever they appear (case-insensitive).
INLINE_BOILERPLATE: list[str] = [
    rf"Haberlerimizi Google{_APOS}da Takip Edin\.?"
    rf"(?:\s*Gelişmelerden anında haberdar olun\.?)?"
    rf"(?:\s*Google{_APOS}da tercih edilen kaynak olarak ekleyin\.?)?",
    rf"Google News{_APOS}[dt][ea] (?:bizi )?takip edin\.?",
    rf"Google Haberler{_APOS}[dt][ea] (?:bizi )?takip edin\.?",
    rf"(?:Bizi )?Google{_APOS}da takip edin\.?",
    r"(?:WhatsApp|Telegram) kanal\w* katıl\w*\.?",
    r"(?:WhatsApp|Telegram) kanal\w* takip edin\.?",
    rf"(?:Bizi )?(?:Instagram|Facebook|Twitter|X|YouTube|Threads|TikTok){_APOS}?(?:da|de|ta|te)? takip edin\.?",
    r"Haberin devamı için tıklayın\.?",
    r"Bültenimize abone ol\w*\.?",
]

# Whole paragraphs to drop: (regex matched at the start, max paragraph length).
DROP_LINES: list[tuple[str, int]] = [
    (r"(?:güncelleme|giriş|yayın|yayımlanma|son güncelleme)\s+tarihi\b", 90),
    (r"(?:güncelleme|giriş)\s*:", 90),
    (r"unvan\s*,", 120),
    (r"yazan\s*,", 120),
    (r"okuma süresi\b", 60),
    (r"haber bilgisi$", 40),
    (r"(?:muhabir|editör|haber merkezi|foto muhabiri|çeviren|kaynak)\s*:", 120),
    (r"fotoğraf altı yazısı\s*,?", 40),
    (r"(?:paylaş|yazdır|link(?:i)? kopyala|facebook|twitter|whatsapp|e-?posta|telegram|linkedin|x)$", 30),
    (r"(?:facebook|twitter|whatsapp|x)['’]?(?:ta|te|da|de|'ta|'te)? paylaş", 60),
    (r"(?:reklam|yorum yap|yorumlar|yorum yaz)$", 30),
    (r"ombudsman['’]?a ulaş", 60),
    (r"bu haberde bir hata mı var\?", 400),
    (r"anadolu ajansı web sitesinde,? aa haber akış", 2000),
    (r"orijinali \S+ olan bu makalenin çevirisinde", 600),
    (r"\*?makalelerdeki fikirler yazarına aittir", 300),
    (r"\[[^\]]{0,200}\]$", 220),
    (r"\*{3,}$", 10),
    (r"[-–—_=]{3,}$", 10),
    (r"\[\d+\]\s", 2000),  # footnote references
    (r"sabah\.com\.tr uygulamamızı indirin", 80),
    (r"(?:uygulamamızı|mobil uygulamamızı) indirin", 80),
    (r"haberler$", 30),
    (r"gündem haberleri$", 40),
]

# Byline and timestamp lines, removed only while they open the body.
LEADING_LINES: list[tuple[str, int]] = [
    (rf"\d{{1,2}}\s+{_MONTHS}\s+\d{{4}}", 60),
    (rf"{_MONTHS}\s+\d{{1,2}},?\s+\d{{4}}", 60),
    (r"\d+\s+(?:saniye|dakika|saat|gün|hafta|ay)\s+önce$", 40),
    (r"\d{1,2}[./]\d{1,2}[./]\d{4}", 40),
    (r"(?:haber merkezi|ankara|[iİ]stanbul|[iİ]zmir)$", 20),
]

# A heading that introduces related-article lists; everything from it on is cut.
RELATED_HEADINGS: list[str] = [
    r"ilgili haberler?",
    r"ilgili içerik(?:ler)?",
    r"ilgili yazılar?",
    r"ayrıca okuyun",
    r"bunu da okuyun",
    r"bunları da okuyun",
    r"bunlar da ilginizi çekebilir",
    r"bunlar da ilgini çekebilir",
    r"diğer haberler",
    r"daha fazla haber",
    r"sizin için seçtik",
    r"önerilen haberler",
    r"öne çıkan haberler",
    r"bu haberler de ilginizi çekebilir",
    r"related (?:articles|stories|news)",
    r"more on this story",
]

# Teaser lines left over at the end (related lists): a trailing date or age.
TRAILING_LINES: list[tuple[str, int]] = [
    (rf".*(?<!\d)\d{{1,2}}\s+{_MONTHS}\s+\d{{4}}$", 260),
    (r".*(?<!\d)\d+\s+(?:dakika|saat|gün|hafta)\s+önce$", 260),
]

# class/id/data-testid words that mark containers which are not article text.
IGNORED_ATTRIBUTE_WORDS: list[str] = [
    "related", "share", "sharing", "social", "byline", "breadcrumb",
    "breadcrumbs", "newsletter", "advert", "advertisement", "ad-slot",
    "ilgili", "recommend", "recommended", "paylas", "more-on",
]

# Keywords that are never topical.
GENERIC_KEYWORDS: set[str] = {
    "son dakika", "fotoğraf", "foto", "foto galeri", "galeri", "video",
    "video haber", "haber", "haberler", "güncel haberler", "flaş haber",
    "anadolu ajansı", "aa", "muhabir", "son dakika haberleri",
    "canlı yayın", "foto haber",
}
# Section names: kept on their own, but a list made mostly of these plus
# generic words is a site-wide navigation list, not article keywords.
NAV_KEYWORDS: set[str] = {
    "ekonomi", "spor", "politika", "kültür sanat", "sinema", "gündem",
    "dünya", "magazin", "teknoloji", "yaşam", "sağlık", "eğitim",
}

_INLINE = [re.compile(p, re.IGNORECASE) for p in INLINE_BOILERPLATE]
_DROP = [(re.compile(p, re.IGNORECASE), n) for p, n in DROP_LINES]
_LEADING = [(re.compile(p, re.IGNORECASE), n) for p, n in LEADING_LINES]
_TRAILING = [(re.compile(p, re.IGNORECASE), n) for p, n in TRAILING_LINES]
_RELATED = re.compile(
    r"(?:" + "|".join(RELATED_HEADINGS) + r")\s*:?", re.IGNORECASE
)
_IGNORED_ATTRS = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in IGNORED_ATTRIBUTE_WORDS) + r")(?![a-z0-9])"
)
_INVISIBLE = re.compile("[​‌‍⁠﻿­]")
_HSPACE = re.compile(r"[^\S\n]+")
_GLUE = re.compile(
    r"(?<=[a-zçğıöşüâîû0-9]{2})([.!?…])(?=[A-ZÇĞİÖŞÜ][a-zçğıöşüâîûA-ZÇĞİÖŞÜ])"
)
_GLUE_DIGIT = re.compile(r"(?<=[a-zçğıöşüâîû]{2})([.!?…])(?=\d)")
_SPACE_BEFORE_PUNCT = re.compile(r" +([,.;:!?])(?=\s|$)")


def has_ignored_attributes(*values: str) -> bool:
    """True when class/id style values name a non-article container."""
    joined = " ".join(v.lower() for v in values if v)
    return bool(joined and _IGNORED_ATTRS.search(joined))


def numeric_ratio(text: str) -> float:
    """Share of characters that are digits or number punctuation."""
    if not text:
        return 0.0
    return sum(ch.isdigit() or ch in ".,%" for ch in text) / len(text)


def fix_glued_sentences(text: str) -> str:
    """Insert the missing space in ``lira.Bu`` style joins."""
    return _GLUE_DIGIT.sub(r"\1 ", _GLUE.sub(r"\1 ", text))


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces per line, drop invisible characters."""
    text = _INVISIBLE.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = []
    for line in text.split("\n"):
        line = _HSPACE.sub(" ", line).strip()
        line = _SPACE_BEFORE_PUNCT.sub(r"\1", line)
        lines.append(line)
    return "\n".join(lines)


def strip_inline_boilerplate(text: str) -> str:
    for pattern in _INLINE:
        text = pattern.sub(" ", text)
    return text


def trim_numeric_tail(paragraph: str) -> str:
    """Cut a dumped table off the end of a long run-on paragraph."""
    size = 200
    if len(paragraph) < 4 * size or numeric_ratio(paragraph) < 0.1:
        return paragraph
    starts = list(range(0, len(paragraph) - size + 1, size // 2))
    dense = [numeric_ratio(paragraph[i : i + size]) > 0.22 for i in starts]
    # Earliest dense window from which at least 80% of the rest is dense too.
    first = next(
        (
            i
            for i in range(len(dense))
            if dense[i] and sum(dense[i:]) >= 0.8 * (len(dense) - i)
        ),
        len(dense),
    )
    if first == len(dense) or len(paragraph) - starts[first] < 300:
        return paragraph
    head = paragraph[: starts[first]]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s|[A-ZÇĞİÖŞÜ0-9])", head)]
    return head[: ends[-1]] if ends else head.rstrip()


def _matches(rules: Iterable[tuple[re.Pattern[str], int]], line: str) -> bool:
    return any(len(line) <= limit and rx.match(line) for rx, limit in rules)


def clean_body(text: str, title: str | None = None) -> str:
    """Normalize and de-boilerplate extracted body text (paragraphs on blank lines)."""
    if not text:
        return ""
    text = normalize_whitespace(strip_inline_boilerplate(fix_glued_sentences(text)))
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    kept: list[str] = []
    for index, line in enumerate(paragraphs):
        if kept and _RELATED.fullmatch(line):
            break
        if _matches(_DROP, line):
            continue
        kept.append(trim_numeric_tail(line))
    paragraphs = kept

    clean_title = (title or "").casefold().strip()
    for _ in range(6):
        if not paragraphs:
            break
        head = paragraphs[0]
        if (clean_title and head.casefold() == clean_title) or _matches(_LEADING, head):
            paragraphs.pop(0)
        else:
            break
    while paragraphs and (
        _matches(_TRAILING, paragraphs[-1])
        or numeric_ratio(paragraphs[-1]) > 0.4
        or paragraphs[-1].endswith(":")  # intro to a table that was removed
    ):
        paragraphs.pop()

    seen: set[str] = set()
    output = []
    for line in paragraphs:
        key = line.casefold()
        if key not in seen:
            seen.add(key)
            output.append(line)
    return "\n\n".join(output)


def filter_keywords(keywords: Iterable[str]) -> list[str]:
    """Remove generic words; drop the whole list if it is site navigation."""
    items = [k for k in keywords if k]
    generic = [k for k in items if k.casefold() in GENERIC_KEYWORDS]
    nav = [k for k in items if k.casefold() in NAV_KEYWORDS]
    if generic and len(generic) + len(nav) >= max(2, len(items) / 2):
        return []
    return [k for k in items if k.casefold() not in GENERIC_KEYWORDS]


__all__ = [
    "clean_body",
    "filter_keywords",
    "fix_glued_sentences",
    "has_ignored_attributes",
    "normalize_whitespace",
    "numeric_ratio",
]
