Implemented CurlSession to bypass Cloudflare on JavDB. Used subprocess to call curl with cookie persistence via temporary files.
## 2026-02-08 Task: javdb_curl
- Successfully replaced `requests.Session` with a custom `CurlSession` using `subprocess.run(['curl', ...])`.
- **Cookie Persistence**: Using `tempfile.NamedTemporaryFile` with `-b` and `-c` flags in `curl` effectively maintains session state across multiple requests, which is crucial for bypassing Cloudflare challenges that rely on session cookies.
- **Response Parsing**: `curl -w "\n%{http_code}\n%{url_effective}"` is a reliable way to extract metadata from the `curl` output without needing complex parsing of headers.
- **Cleanup**: Implementing `__del__` in the session class ensures that temporary cookie files are removed, preventing disk clutter.
- **Compatibility**: Mimicking the `requests.Response` interface (`.text`, `.content`, `.status_code`, `.url`, `.ok`) allowed for a drop-in replacement with minimal changes to the existing scraping logic.
