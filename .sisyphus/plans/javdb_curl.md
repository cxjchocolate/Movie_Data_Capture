# Plan: Refactor Javdb to use Curl for Cloudflare Bypass

## TL;DR

> **Quick Summary**: Replace `requests` with a custom `CurlSession` wrapper that executes `curl` via subprocess, mimicking the `requests` interface to minimize code changes while bypassing Cloudflare.
> 
> **Deliverables**:
> - Modified `scrapinglib/javdb.py` with `CurlSession` and `CurlResponse` classes.
> - Replacement of `request_session` with `CurlSession` in `Javdb.search`.
> 
> **Estimated Effort**: Short
> **Parallel Execution**: NO
> **Critical Path**: Implement Wrapper → Replace Usage → Verify

---

## Context

### Original Request
Replace `self.session.get` in `javdb.py` with a `curl` command to prevent Cloudflare interception.

### Technical Analysis
- **Current State**: Uses `requests.Session` which handles cookies and headers automatically.
- **Challenge**: `curl` is stateless. Cloudflare requires session persistence (cookies).
- **Solution**: Implement a `CurlSession` class that:
  - Manages a temporary cookie jar file (`-c` / `-b`).
  - Maps `requests` proxy dictionaries to `curl -x`.
  - Parses `curl` output to mimic `requests.Response` (`.text`, `.status_code`, `.url`).

### Metis Review
**Identified Gaps** (addressed):
- **Cookie Persistence**: Essential for Cloudflare. Solved via `tempfile` cookie jar.
- **Response Parsing**: Need status code and effective URL. Solved via `curl -w`.
- **Encoding**: `curl` output is bytes. Solved via manual UTF-8 decoding in wrapper.

---

## Work Objectives

### Core Objective
Enable `javdb.py` to fetch data from Javdb bypassing Cloudflare by using `curl`.

### Definition of Done
- [x] `Javdb.search` uses `curl` instead of `requests`.
- [x] Cookies (both static and session) are preserved across requests.
- [x] Response text is correctly decoded.
- [x] Proxies are correctly passed to `curl`.

### Guardrails
- **MUST** use `subprocess` (no `curl_cffi` dependency added).
- **MUST** clean up temporary cookie files.
- **MUST NOT** break existing parsing logic (return types must match).

---

## Verification Strategy

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
> ALL tasks must be verifiable by the agent.

### Test Decision
- **Infrastructure exists**: No unit tests found for this file.
- **Automated tests**: Tests-after (Agent Verification).
- **Framework**: `unittest` / `pytest` not required, script-based verification.

### Agent-Executed QA Scenarios

```
Scenario: Verify CurlSession Interface
  Tool: Bash (python3 -c)
  Preconditions: None
  Steps:
    1. Run python script:
       from scrapinglib.javdb import CurlSession
       s = CurlSession(cookies={'test':'1'})
       resp = s.get('https://httpbin.org/get')
       print(f"Status: {resp.status_code}")
       print(f"User-Agent: {resp.text}")
    2. Assert stdout contains "Status: 200"
    3. Assert stdout contains "curl" (in User-Agent if set, or just successful fetch)
  Expected Result: Script runs without error and fetches data.
  Evidence: Terminal output.

Scenario: Verify Cookie Persistence
  Tool: Bash (python3 -c)
  Preconditions: None
  Steps:
    1. Run python script:
       from scrapinglib.javdb import CurlSession
       s = CurlSession()
       # First request sets cookie
       s.get('https://httpbin.org/cookies/set/test_cookie/123')
       # Second request reads cookie
       resp = s.get('https://httpbin.org/cookies')
       print(resp.text)
    2. Assert stdout contains "test_cookie"
    3. Assert stdout contains "123"
  Expected Result: Cookies persisted between requests.
  Evidence: Terminal output.
```

---

## TODOs

- [x] 1. Implement Curl Wrapper Classes in `javdb.py`

  **What to do**:
  - Add imports: `subprocess`, `tempfile`, `os`, `shutil`.
  - Add `CurlResponse` class:
    - `__init__(self, content, status_code, url)`
    - Properties: `text` (decoded), `content` (bytes), `status_code` (int), `url` (str), `ok` (bool).
  - Add `CurlSession` class:
    - `__init__(self, cookies, proxies, verify)`: Create temp cookie file.
    - `get(self, url)`: Execute `curl`.
      - Build command: `curl -L -s --compressed -w "\n%{http_code}\n%{url_effective}" -o - [url]`
      - Handle proxies: `-x [proxy_url]`
      - Handle cookies: `-b [jar] -c [jar]` AND `-H "Cookie: [static_cookies]"`
      - Handle headers: `-H "User-Agent: ..."`
    - `__del__`: Remove temp file.

  **Refactoring**:
  - Modify `Javdb.search` to use `CurlSession` instead of `request_session`.

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: [`git-master`] (for code editing context)

  **References**:
  - `scrapinglib/javdb.py:66` - `search` method to modify.
  - `scrapinglib/httprequest.py` - Check if `G_USER_AGENT` is available to import.

  **Acceptance Criteria**:
  - [x] `CurlSession` class exists in `javdb.py`.
  - [x] `Javdb.search` instantiates `CurlSession`.
  - [x] `curl` command constructed with correct flags (`-L`, `-s`, `-b`, `-c`, `-x`).
  - [x] Python script verification passes (see QA Scenarios).

---

## Success Criteria

### Verification Commands
```bash
python3 -c "from scrapinglib.javdb import CurlSession; s=CurlSession(); print(s.get('https://example.com').status_code)"
# Expected: 200
```

### Final Checklist
- [x] `requests` dependency removed from `Javdb.search` logic (though import remains for other files).
- [x] Temp files cleaned up.
- [x] Cloudflare bypass potential maximized (User-Agent + Headers).
