# JavDB Cloudflare Bypass (curl_cffi) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the subprocess-based `CurlSession` in `scrapinglib/javdb.py` with a `curl_cffi` session that impersonates Chrome's TLS/HTTP2 fingerprint, so javdb scraping passes Cloudflare and stays passed.

**Architecture:** `CurlSession` becomes a thin wrapper around `curl_cffi.requests.Session(impersonate="chrome")`. The wrapper preserves the existing `.get(url)` → response-with-`.text/.status_code/.url/.ok` interface, so all callers (`search`, `queryNumberUrl`, `getActorPhoto`) are unchanged. A new `_is_cloudflare_blocked` helper detects Cloudflare challenge pages/status codes and raises a clear error instead of silently parsing challenge HTML.

**Tech Stack:** Python 3.12, `curl_cffi` (new dependency), `lxml`, stdlib `unittest` for the one unit test (no pytest added).

## Global Constraints

- Single strategy: curl_cffi with `impersonate="chrome"` only. No fallback chain, no fingerprint rotation.
- Scope is `scrapinglib/javdb.py` plus one entry in `requirements.txt`. Do not touch `storyline.py`, other scrapers, or `httprequest.py`.
- No new test framework: use stdlib `unittest`, run via `python3 -m unittest`.
- Must not change the response interface that `search`/`queryNumberUrl`/`getActorPhoto` rely on (`.text`, `.status_code`, `.url`, `.ok`).
- Remove now-unused imports (`subprocess`, `tempfile`, `os`, `G_USER_AGENT`) — the codebase tracks unused-symbol cleanup (commit `8d961a4`).

---

## File Structure

- **Modify:** `scrapinglib/javdb.py` — rewrite `CurlSession` (lines 13–85) on curl_cffi; add `_is_cloudflare_blocked` / `_raise_if_blocked` to `Javdb`; wire detection into `search` and `queryNumberUrl`; fix imports.
- **Modify:** `requirements.txt` — add `curl_cffi`.
- **Create:** `tests/test_javdb_cloudflare.py` — stdlib `unittest` for the pure detection logic (no network).

---

### Task 1: Add curl_cffi dependency and rewrite CurlSession

**Files:**
- Modify: `requirements.txt`
- Modify: `scrapinglib/javdb.py:1-85` (imports + `CurlResponse`/`CurlSession` block)

**Interfaces:**
- Consumes: `curl_cffi.requests.Session` (third-party), `G_DEFAULT_TIMEOUT` from `.httprequest`.
- Produces: `CurlSession(cookies=None, proxies=None, verify=True, impersonate="chrome")` with `.get(url, **kwargs)` returning a curl_cffi response object exposing `.text`, `.content`, `.status_code`, `.url`, `.ok`. Cookies persist across requests via `session.cookies`.

- [ ] **Step 1: Add curl_cffi to requirements**

In `requirements.txt`, add `curl_cffi` on its own line (alphabetical-ish placement near `cloudscraper` is fine):

```
curl_cffi
```

- [ ] **Step 2: Install the dependency**

Run: `pip install curl_cffi`
Expected: installs successfully; `python3 -c "import curl_cffi; print(curl_cffi.__version__)"` prints a version.

- [ ] **Step 3: Replace the imports at the top of javdb.py**

Replace lines 1–10 of `scrapinglib/javdb.py`:

```python
# -*- coding: utf-8 -*-

import re
import subprocess
import tempfile
import os
from urllib.parse import urljoin
from lxml import etree
from .httprequest import G_USER_AGENT
from .parser import Parser
```

with:

```python
# -*- coding: utf-8 -*-

import re
from urllib.parse import urljoin
from lxml import etree
from curl_cffi import requests as cffi_requests
from .httprequest import G_DEFAULT_TIMEOUT
from .parser import Parser
```

This drops `subprocess`, `tempfile`, `os`, and `G_USER_AGENT` (all only used by the old curl shell-out) and adds `cffi_requests` + `G_DEFAULT_TIMEOUT`.

- [ ] **Step 4: Replace CurlResponse + CurlSession with the new wrapper**

Replace the entire `CurlResponse` and `CurlSession` block (lines 13–85, from `class CurlResponse:` through the end of `CurlSession.__del__`) with:

```python
class CurlSession:
    """curl_cffi-backed session that impersonates a real Chrome TLS/HTTP2
    fingerprint to bypass Cloudflare. Drop-in replacement for the previous
    subprocess-based curl wrapper; the underlying curl_cffi response objects
    expose the same `.text/.content/.status_code/.url/.ok` interface."""

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

- [ ] **Step 5: Verify the module imports cleanly**

Run: `python3 -c "from scrapinglib.javdb import Javdb, CurlSession; print('ok')"`
Expected: prints `ok` with no import errors.

- [ ] **Step 6: Verify no stale references to removed symbols remain**

Run: `grep -nE "subprocess|tempfile|^import os|G_USER_AGENT|CurlResponse|cookie_path|NamedTemporaryFile" scrapinglib/javdb.py`
Expected: no matches (all lines that referenced the old machinery are gone).

- [ ] **Step 7: Commit**

```bash
git add scrapinglib/javdb.py requirements.txt
git commit -m "refactor: replace subprocess curl with curl_cffi in javdb to bypass Cloudflare"
```

---

### Task 2: Add Cloudflare-block detection and wire it in (TDD)

**Files:**
- Create: `tests/test_javdb_cloudflare.py`
- Modify: `scrapinglib/javdb.py` — add helpers to `Javdb`, wire into `search` and `queryNumberUrl`.

**Interfaces:**
- Consumes: `CurlSession` response objects (`.status_code`, `.text`) from Task 1.
- Produces: `Javdb._is_cloudflare_blocked(resp) -> bool` and `Javdb._raise_if_blocked(resp) -> None` (raises on block).

- [ ] **Step 1: Write the failing test**

Create `tests/test_javdb_cloudflare.py`:

```python
import unittest


class FakeResponse:
    """Duck-typed stand-in for a curl_cffi response (has .status_code/.text)."""
    def __init__(self, status_code, text=''):
        self.status_code = status_code
        self.text = text


class JavdbCloudflareDetectionTest(unittest.TestCase):
    def _make(self):
        # Bypass Parser.__init__; detection only needs self.number.
        from scrapinglib.javdb import Javdb
        j = Javdb.__new__(Javdb)
        j.number = 'TEST-001'
        return j

    def test_blocked_by_status_403(self):
        j = self._make()
        self.assertTrue(j._is_cloudflare_blocked(FakeResponse(403, 'anything')))

    def test_blocked_by_status_429(self):
        j = self._make()
        self.assertTrue(j._is_cloudflare_blocked(FakeResponse(429, '')))

    def test_blocked_by_status_503(self):
        j = self._make()
        self.assertTrue(j._is_cloudflare_blocked(FakeResponse(503, '')))

    def test_blocked_by_challenge_text_just_a_moment(self):
        j = self._make()
        html = '<html><head><title>Just a moment...</title></head></html>'
        self.assertTrue(j._is_cloudflare_blocked(FakeResponse(200, html)))

    def test_blocked_by_challenge_text_cf_platform(self):
        j = self._make()
        html = '<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/jsch/v1"></script>'
        self.assertTrue(j._is_cloudflare_blocked(FakeResponse(200, html)))

    def test_not_blocked_normal_page(self):
        j = self._make()
        html = '<html><head><title>ABC-123 | JavDB</title></head></html>'
        self.assertFalse(j._is_cloudflare_blocked(FakeResponse(200, html)))

    def test_raise_if_blocked_raises(self):
        j = self._make()
        with self.assertRaises(Exception):
            j._raise_if_blocked(FakeResponse(403, 'blocked'))

    def test_raise_if_blocked_passes_when_clean(self):
        j = self._make()
        j._raise_if_blocked(FakeResponse(200, '<html>ok</html>'))  # no exception


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest tests.test_javdb_cloudflare -v`
Expected: FAIL / ERROR with `AttributeError: 'Javdb' object has no attribute '_is_cloudflare_blocked'`.

- [ ] **Step 3: Add the detection helpers to Javdb**

In `scrapinglib/javdb.py`, add these two methods to the `Javdb` class. Place them immediately after `updateCore` (after line ~142, before `def search`):

```python
    def _is_cloudflare_blocked(self, resp):
        """True if the response is a Cloudflare block / challenge page."""
        if resp.status_code in (403, 429, 503):
            return True
        text = resp.text
        return ('Just a moment' in text
                or 'cf-browser-verification' in text
                or 'challenge-platform' in text
                or '<title>Attention Required! | Cloudflare</title>' in text)

    def _raise_if_blocked(self, resp):
        if self._is_cloudflare_blocked(resp):
            raise Exception(
                f'[!] {self.number}: javdb blocked by Cloudflare (status {resp.status_code}). '
                f'Try a proxy or update curl_cffi impersonation target.')
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m unittest tests.test_javdb_cloudflare -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Wire detection into queryNumberUrl**

In `Javdb.queryNumberUrl`, find the line:

```python
            resp = self.session.get(javdb_url)
            self.querytree = etree.fromstring(resp.text, etree.HTMLParser()) 
```

Change to insert the block check before parsing:

```python
            resp = self.session.get(javdb_url)
            self._raise_if_blocked(resp)
            self.querytree = etree.fromstring(resp.text, etree.HTMLParser())
```

(Also drops the trailing space after `etree.HTMLParser()`.)

- [ ] **Step 6: Wire detection into search**

In `Javdb.search`, find the line:

```python
        self.deatilpage = self.session.get(self.detailurl).text
```

Replace with:

```python
        resp = self.session.get(self.detailurl)
        self._raise_if_blocked(resp)
        self.deatilpage = resp.text
```

This must come *before* the existing login-required check (`if '此內容需要登入才能查看或操作' in self.deatilpage ...`) so a blocked page is not misread as "needs login".

- [ ] **Step 7: Verify the module still imports and tests still pass**

Run: `python3 -c "from scrapinglib.javdb import Javdb; print('ok')"` then `python3 -m unittest tests.test_javdb_cloudflare -v`
Expected: `ok`, then 8 PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/test_javdb_cloudflare.py scrapinglib/javdb.py
git commit -m "feat: detect Cloudflare blocks in javdb and fail fast with a clear error"
```

---

### Task 3: Live smoke verification and final cleanup check

**Files:**
- No file changes unless verification reveals a problem.

**Interfaces:**
- Consumes: the finished `Javdb` scraper from Tasks 1–2.

- [ ] **Step 1: Live scrape smoke test (requires network; proxy optional)**

Run a real scrape through the public API. Use a known-valid number; set a proxy if your network requires one to reach javdb:

```bash
python3 -c "
from scrapinglib import search
import json
data = search('SSIS-001', sources='javdb')
if not data:
    print('NO DATA')
else:
    d = json.loads(data)
    print('number:', d.get('number'))
    print('title:', d.get('title'))
    print('cover:', d.get('cover'))
    print('source:', d.get('source'))
"
```

Expected: prints a non-empty `number`, `title`, `cover`, and `source: javdb` — no Cloudflare exception raised. If a Cloudflare exception is raised, confirm the proxy/impersonation target and re-run; if it persists, that is a real failure to investigate (not a silent empty result).

- [ ] **Step 2: Confirm the Cloudflare-detection path is reachable (negative check)**

Sanity-check the detection logic against the live response object type — run:

```bash
python3 -c "
from scrapinglib.javdb import Javdb
from scrapinglib.httprequest import G_DEFAULT_TIMEOUT
from curl_cffi import requests as cffi_requests
s = cffi_requests.Session(impersonate='chrome')
r = s.get('https://javdb.com/search?q=SSIS-001&f=all', timeout=G_DEFAULT_TIMEOUT)
j = Javdb.__new__(Javdb); j.number='SSIS-001'
print('status:', r.status_code, 'blocked:', j._is_cloudflare_blocked(r))
"
```

Expected: `status: 200`, `blocked: False`. (If `blocked: True` here, the impersonation is not passing Cloudflare — investigate before finishing.)

- [ ] **Step 3: Final unused-import sweep**

Run: `grep -nE "^import subprocess|^import tempfile|^import os|G_USER_AGENT" scrapinglib/javdb.py`
Expected: no matches.

Run: `git status`
Expected: clean working tree (all changes committed in Tasks 1–2) unless Step 1 revealed a fix.

- [ ] **Step 4: Commit any verification fixes (if any)**

Only if Step 1/2 revealed a problem requiring a code change:

```bash
git add -A
git commit -m "fix: javdb cloudflare bypass verification adjustments"
```

Otherwise this step is a no-op — the implementation is already committed.

---

## Self-Review

**1. Spec coverage:**
- Replace CurlSession engine with curl_cffi → Task 1. ✅
- Remove CurlResponse, subprocess/tempfile/os, temp cookie file, `__del__` → Task 1 Steps 3–4, verified Step 6. ✅
- Drop `G_USER_AGENT` import → Task 1 Step 3, verified Task 3 Step 3. ✅
- Unchanged callers → Task 1 preserves interface; Task 2 Step 6 changes `search` minimally (captures resp, still assigns `.text`). ✅
- `requirements.txt` adds curl_cffi → Task 1 Step 1. ✅
- Cloudflare-block detection helper + raise → Task 2 Step 3. ✅
- Wired into queryNumberUrl and search (before login check) → Task 2 Steps 5–6. ✅
- Timeout = G_DEFAULT_TIMEOUT → Task 1 Step 4 (`kwargs.setdefault('timeout', ...)`). ✅
- Cookies/proxies/verify mapping → Task 1 Step 4. ✅
- Testing: import check, live smoke, proxy path, regression, DoD → Tasks 1–3. ✅
- Out of scope respected (storyline/other scrapers untouched) → no task touches them. ✅

**2. Placeholder scan:** No TBD/TODO/vague steps. All code blocks are complete. ✅

**3. Type consistency:** `_is_cloudflare_blocked(resp)` and `_raise_if_blocked(resp)` signatures match between Task 2 Step 1 (test), Step 3 (impl), Step 5/6 (call sites). `CurlSession.get` returns a curl_cffi response with `.text/.status_code` used consistently. ✅
