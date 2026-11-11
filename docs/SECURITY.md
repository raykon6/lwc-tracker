# Security notes

Verity reads two kinds of input it did not write: the uploaded roster and the HTML of public profile pages. Both are treated as hostile. This document lists the threats considered and where each control lives.

## Threat model

| # | Threat | Control | Where |
|---|---|---|---|
| 1 | **SSRF**: a roster cell points the server at an internal or attacker host (`169.254.169.254`, `user@evil`, `evil\@skills.google`, odd ports, path tricks) | The fetcher never requests user input. A strict UUID is extracted, and the only URL ever built is `https://www.skills.google/public_profiles/<uuid>`. Host allowlist, no credentials, no ports other than 80/443, exact path pattern. `canonical_profile_url()` refuses unvalidated IDs | `security.py` |
| 2 | **Redirect abuse**: upstream redirects somewhere else | Redirects are never followed. A 3xx means "not found or not public" | `fetcher.py` |
| 3 | **CSV / formula injection** in exported spreadsheets | Cells starting with `= + - @ \t \r \| %` are prefixed with `'` | `security.safe_cell`, `export.py` |
| 4 | **Stored XSS** through names, badge titles or errors | The UI writes untrusted text only with `textContent`; no `innerHTML`. Strict CSP: `script-src 'self'`, no inline scripts, `object-src 'none'`, `frame-ancestors 'none'`. Profile links are re-checked against the canonical pattern before they become `href`s, and open with `rel="noopener noreferrer"` | `web/static/app.js`, `web/app.py` |
| 5 | **CSRF** | State-changing requests need the `X-Verity-Request: 1` header, which a cross-site form cannot send without a CORS preflight, and CORS is never granted. A foreign `Origin` is rejected | `web/app.py` |
| 6 | **DNS rebinding** against the local server | `TrustedHostMiddleware` allows only localhost names, plus `--public-name` when one is set | `web/app.py`, `cli.py` |
| 7 | **Resource exhaustion**: large or slow uploads, floods | Content-Length required and capped; 1 MB / 5,000-row roster limits; binary files rejected; per-client sliding-window limits (20 uploads, 10 runs, 300 polls and 30 exports a minute); at most 2 active runs; Uvicorn concurrency limit and short keep-alive | `roster.py`, `web/app.py`, `cli.py` |
| 8 | **Hostile or huge upstream pages** | Streamed download with a 2 MB cap; `text/html` only; parsing with lxml (no scripts run); at most 1,000 badge cards read; parser exceptions are contained per worker | `fetcher.py`, `parser.py`, `engine.py` |
| 9 | **Hammering the upstream site** (and getting blocked) | Global token bucket (1 req/s, burst 2) shared across runs; a 429 pauses every worker for `Retry-After`; exponential backoff with jitter; circuit breaker after 8 consecutive failures; 15-minute cache of successful parses | `fetcher.py`, `engine.py` |
| 10 | **Unauthorised access** when shared on a network | Binds to `127.0.0.1` by default. Beyond localhost a bearer token is mandatory (generated if not set) and compared in constant time. The token is kept in `sessionStorage`, not cookies | `cli.py`, `web/app.py` |
| 11 | **Information leakage** | Generic error messages with a reference ID; stack traces only in server logs; OpenAPI and docs endpoints disabled; no `Server` header; emails masked and profile IDs truncated in logs; `Referrer-Policy: no-referrer`; `Cache-Control: no-store` on API responses | `web/app.py`, `security.py` |
| 12 | **Unguessable state** | Roster and run IDs come from `secrets.token_urlsafe(18)`, are format-checked on every request, and expire after an hour | `jobs.py`, `web/app.py` |
| 13 | **Hidden or bidi characters** in names and links (Trojan Source-style spoofing) | Control and bidi-override characters are rejected in links and stripped from displayed text; Unicode is NFKC-normalised | `security.py` |
| 14 | **Config tampering** | Campaign rules live server-side in `campaign.toml`. The browser can read them but cannot change them; all values are clamped | `config.py` |
| 15 | **Ambient proxy or credential leakage** in outbound requests | `requests.Session.trust_env = False`, so environment proxies and `.netrc` are ignored; an honest User-Agent is sent | `fetcher.py` |

## Data handling

- Only public profile pages are read. No sign-in, cookies or Google APIs are used.
- Rosters and results are held in process memory and expire after `job_ttl_seconds` (one hour by default). Nothing is written to disk unless you export.
- `robots.txt` on skills.google allows `/public_profiles`. The default pace of 1 request per second is deliberately conservative.

## Known limits

- The badge parser depends on the current profile page markup. If the layout changes, rows show **Unreadable page** instead of silently reporting 0 badges; update `parser.py`.
- The inbound rate limiter keys on the TCP client address. Behind a reverse proxy, every client shares one key unless you terminate rate limiting at the proxy.
- Serving on a network uses plain HTTP unless you put a TLS-terminating reverse proxy in front.
