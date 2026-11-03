"""Keyless web-search + page-text layer.

Primary backend: DuckDuckGo HTML endpoint (no key, no JS). Fallback: a
small set of public SearXNG instances (JSON). Also a plain HTTP fetcher
that strips HTML to text for source verification.
"""
from __future__ import annotations

import base64
import html as _html
import json
import re
import ssl
import time
import urllib.parse
import urllib.request

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_SX_INSTANCES = [
    "https://searx.be",
    "https://search.busytips.net",
    "https://searx.tiekoetter.com",
    "https://paulgo.io",
    "https://search.ononoki.com",
]
_ctx = ssl.create_default_context()
# global rate limit so we don't hammer the keyless backends (keeps runs fast +
# avoids throttling/hang). All HTTP goes through _http_get.
_MIN_INTERVAL = 1.5
_last_req = [0.0]
_search_cache: dict = {}


def _throttle() -> None:
    wait = _MIN_INTERVAL - (time.time() - _last_req[0])
    if wait > 0:
        time.sleep(wait)
    _last_req[0] = time.time()


def _http_get(url: str, timeout: int = 20) -> str:
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx) as r:
        return r.read().decode("utf-8", "ignore")


def _ddg_unwrap(href: str) -> str:
    m = re.search(r"uddg=([^&]+)", href)
    if m:
        try:
            return urllib.parse.unquote(m.group(1))
        except Exception:
            pass
    return href


def _ddg(query: str, n: int = 6) -> list[dict]:
    out: list[dict] = []
    q = urllib.parse.quote(query)
    try:
        raw = _http_get("https://html.duckduckgo.com/html/?q=" + q, 20)
    except Exception as e:  # noqa: BLE001
        return [{"title": "", "url": "", "snippet": f"DDG_ERR {e}"}]
    blocks = re.split(r'class="result results_links', raw)
    for b in blocks[1:]:
        a = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        s = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', b, re.S)
        if not a:
            continue
        url = _ddg_unwrap(a.group(1))
        title = re.sub(r"<[^>]+>", "", a.group(2))
        snip = re.sub(r"<[^>]+>", "", s.group(1)) if s else ""
        out.append({"title": _html.unescape(title), "url": url, "snippet": _html.unescape(snip)})
        if len(out) >= n:
            break
    return out


def _searx(query: str, n: int = 6) -> list[dict]:
    q = urllib.parse.quote(query)
    # fast last-resort: few instances, short timeout
    for base in _SX_INSTANCES[:2]:
        try:
            data = json.loads(_http_get(f"{base}/search?format=json&q={q}", 6))
            res = data.get("results", [])
            if res:
                return [{"title": r.get("title", ""), "url": r.get("url", ""),
                        "snippet": r.get("content", "")} for r in res[:n]]
        except Exception:  # noqa: BLE001
            continue
    return []


def _ddgs(query: str, n: int = 6) -> list[dict] | None:
    """Primary backend: the maintained `ddgs` client, retried with backoff.

    Returns a (possibly empty) list on success, None on hard failure."""
    try:
        from ddgs import DDGS
    except Exception:  # noqa: BLE001
        return None
    for attempt in range(3):
        try:
            with DDGS(timeout=8) as d:
                res = list(d.text(query, max_results=n))
            return [{"title": r.get("title", ""),
                     "url": (r.get("href") or r.get("url", "")),
                     "snippet": (r.get("body") or r.get("snippet", ""))}
                    for r in res]
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
    return None


def search(query: str, n: int = 6) -> list[dict]:
    """Return up to n {title,url,snippet} dicts for `query` (keyless).

    Backends in order: ddgs (retried), DuckDuckGo HTML, SearXNG.
    """
    key = (query.lower(), n)
    if key in _search_cache:
        return _search_cache[key]
    res = _ddgs(query, n)
    if res is not None:
        _search_cache[key] = res
        return res
    res = _ddg(query, n)
    if res and not (len(res) == 1 and res[0].get("url") == ""
                    and "ERR" in res[0].get("snippet", "")):
        _search_cache[key] = res
        return res
    res = _searx(query, n)
    if res:
        _search_cache[key] = res
        return res
    out = [{"title": "", "url": "", "snippet": f"SEARCH_FAILED: {query}"}]
    _search_cache[key] = out
    return out


_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_WS_RE = re.compile(r"\s+")


def fetch_text(url: str, timeout: int = 10, max_chars: int = 40000) -> str:
    """Fetch a URL and return its visible text (tags stripped), best-effort."""
    try:
        raw = _http_get(url, timeout)
    except Exception:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = _WS_RE.sub(" ", text)
    return text[:max_chars]


def domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return (m.group(1) or "").lower() if m else ""


def norm_num(s: str) -> str:
    """Normalize for matching: lowercase, drop commas + stray spaces."""
    return re.sub(r"[,\s]", "", (s or "").lower())


def value_in_text(text: str, value: str) -> bool:
    """Boundary-aware check that `value` appears in `text`.

    Numbers match as whole digit-runs, so '45' does NOT match inside '145',
    and adjacent table cells ('1860 771') do not cause a false negative.
    Commas are treated as thousands separators ('7,239,881' == '7239881');
    spaces are kept as delimiters. Non-numeric values match as
    case-insensitive substrings.
    """
    v = str(value).strip()
    if not v:
        return False
    digits = re.sub(r"[,\s]", "", v)  # '7,239,881' -> '7239881'
    low = (text or "").lower()
    if digits and digits.isdigit() and "." not in v:
        # keep spaces (run delimiters), drop only commas
        runs = re.findall(r"\d+", low.replace(",", ""))
        tv = digits.lstrip("0") or "0"
        return any(r == tv for r in runs)
    return v.lower() in low
