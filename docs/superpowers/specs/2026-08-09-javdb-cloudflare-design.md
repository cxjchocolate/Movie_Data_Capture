# Design: JavDB Cloudflare Bypass via curl_cffi

**Date:** 2026-08-09
**Scope:** `scrapinglib/javdb.py` only
**Status:** Approved (pending spec review)

## Problem

`scrapinglib/javdb.py` scrapes javdb.com, which is protected by Cloudflare. The
previous fix (commit `6146790`, "refactor: replace requests with curl in
javdb.py to bypass cloudflare") replaced `requests.Session` with a custom
`CurlSession` that shells out to the system `curl` binary. That worked briefly
and is now blocked again.

**Root cause:** Cloudflare's modern protection fingerprints the TLS handshake
(JA3/JA4) and HTTP/2 settings — it does not rely on the `User-Agent` string.
Plain `curl` has a distinctive, stable TLS fingerprint regardless of the `-A`
browser UA it sends. Cloudflare recognizes "this is curl, not a browser" from
the handshake alone and issues a challenge/block. This is why the curl bypass
could not hold. The prior plan's guardrail — "MUST use subprocess (no curl_cffi
dependency added)" — confined the solution to plain curl and so could not
address the root cause.

## Solution

Replace the `CurlSession` engine from `subprocess.run(['curl', ...])` to
`curl_cffi.requests.Session(impersonate="chrome")`. curl_cffi is a Python
binding to curl-impersonate, which sends a TLS + HTTP/2 fingerprint identical to
a real Chrome browser. This is the standard, robust approach to bypassing
Cloudflare's TLS-based challenge.

Single strategy — no fallback chain, no fingerprint rotation (per decision).

## Component Changes

### `CurlSession` (rewritten)

Becomes a thin wrapper around `curl_cffi.requests.Session`:

```python
from curl_cffi import requests as cffi_requests
from .httprequest import G_DEFAULT_TIMEOUT

class CurlSession:
    def __init__(self, cookies=None, proxies=None, verify=True, impersonate="chrome"):
        self.session = cffi_requests.Session(impersonate=impersonate)
        if isinstance(cookies, dict) and cookies:
            for k, v in cookies.items():
                self.session.cookies.set(k, v)
        if proxies:
            self.session.proxies = proxies
        self.session.verify = verify

    def get(self, url, **kwargs):
        kwargs.setdefault('timeout', G_DEFAULT_TIMEOUT)
        return self.session.get(url, **kwargs)
```

- Constructor wires cookies / proxies / verify from the existing params, matching
  the old behavior (default cookies `{'over18':'1', 'theme':'auto', 'locale':'zh'}`
  from `updateCore`, or user-supplied `dbcookies`).
- `impersonate="chrome"` sets a Chrome-matching TLS+HTTP2 fingerprint and UA.
  It is a constructor default so the impersonation target lives in one place.
- `get()` adds an explicit `timeout` (10s, `G_DEFAULT_TIMEOUT`); the old curl
  call had no timeout and could hang indefinitely.

### Removed

- `CurlResponse` class — curl_cffi's response object already exposes `.text`,
  `.content`, `.status_code`, `.url`, `.ok`, so the mimic is redundant.
- `subprocess`, `tempfile`, `os` imports — no longer used.
- `G_USER_AGENT` import — was only used in the old curl `-A` flag; impersonation
  supplies its own browser-matching UA, so the import is now unused and dropped.
- Temporary cookie-file logic (`NamedTemporaryFile`, `-b`/`-c`, `__del__`
  cleanup, manual byte-splitting parser) — curl_cffi persists cookies across
  requests via `session.cookies`, replacing the cookie-jar file approach.

### Unchanged callers

Because curl_cffi's response interface matches what `CurlResponse` exposed, these
callers need no changes:

- `search()`: `self.session = CurlSession(cookies=self.cookies, proxies=self.proxies, verify=self.verify)`; `self.deatilpage = self.session.get(self.detailurl).text`
- `queryNumberUrl()`: `resp = self.session.get(javdb_url)`; uses `resp.text`, `resp.url`, `resp.status_code`
- `getActorPhoto()` / `getaphoto()`: `session.get(url).text`

### `requirements.txt`

Add `curl_cffi`.

## Cloudflare-Block Detection

A blocked request currently returns Cloudflare's challenge HTML, which silently
flows through `etree.fromstring` and yields empty fields or a misleading "No
search results" / "needs login" error. Add explicit detection that fails fast
with a clear message.

Helper on `Javdb`:

```python
def _is_cloudflare_blocked(self, resp):
    if resp.status_code in (403, 429, 503):
        return True
    text = resp.text
    return ('Just a moment' in text
            or 'cf-browser-verification' in text
            or 'challenge-platform' in text
            or '<title>Attention Required! | Cloudflare</title>' in text)
```

On detection, raise:

```python
raise Exception(f'[!] {self.number}: javdb blocked by Cloudflare (status {resp.status_code}). Try a proxy or update curl_cffi impersonation target.')
```

**Call sites:**

- `queryNumberUrl` — after `resp = self.session.get(javdb_url)`, before parsing
  the search tree.
- `search` — after fetching `self.deatilpage`, before the existing login-required
  check (`'此內容需要登入才能查看或操作'`). A blocked detail page must not be
  misread as "needs login". Login detection stays intact and separate.

## Config & Edge Cases

- **Impersonation target:** `chrome` (curl_cffi's latest Chrome profile), as a
  constructor default. Single point of change. No rotation.
- **Cookies:** default `{'over18':'1', 'theme':'auto', 'locale':'zh'}` or
  user-supplied `dbcookies` flow through unchanged via `CurlSession(cookies=...)`.
  curl_cffi persists them across requests via `session.cookies`, equivalent to
  the old `-b`/`-c` cookie-jar behavior.
- **Proxies & verify:** mapped directly to `session.proxies` / `session.verify`.
  Proxy dict shape (`{'https': ..., 'http': ...}`) is compatible with curl_cffi.
- **Timeout:** explicit `G_DEFAULT_TIMEOUT` (10s) added — small robustness
  improvement over the old timeout-less curl call.
- **`getActorPhoto`:** repeated `self.session.get(url)` per actor — unchanged,
  reuses the same session; cookies persist. No special handling.

## Testing & Verification

No test framework in the repo (no `tests/`, no pytest config). Verification is
manual plus a self-contained smoke check.

1. **Import check:** `python3 -c "from scrapinglib.javdb import Javdb"` —
   confirms no syntax/import errors and curl_cffi is installed.
2. **Live smoke test:** scrape a known number through the project's existing
   CLI entrypoint. Verify: populated result dict (non-empty title/cover/number),
   `status_code == 200`, Cloudflare-detection path not triggered. A blocked
   response now raises the explicit Cloudflare exception instead of returning
   empty fields.
3. **Proxy path:** with a proxy configured, confirm `session.proxies` routes
   correctly.
4. **Regression:** confirm the three shared-session callers (`search`,
   `queryNumberUrl`, `getActorPhoto`) all work against real javdb pages.

## Definition of Done

- `curl_cffi` added to `requirements.txt` and importable.
- `CurlSession` rewritten on curl_cffi; `CurlResponse`, subprocess/tempfile/`os`
  imports, temp cookie-file logic, and `__del__` removed.
- Cloudflare-block detection raises a clear error in both `search` and
  `queryNumberUrl`.
- Live scrape of a sample number returns populated fields with no false
  Cloudflare error.
- No unused imports (`subprocess`, `tempfile`, `os`, `G_USER_AGENT` all gone).

## Out of Scope

- `storyline.py` (uses cloudscraper for javdb storyline) — separate concern.
- Other scrapers — untouched.
- Fingerprint rotation / fallback chain — not included (single-strategy decision).
