# curl_cffi Analysis — Desktop Agent Integration

## What curl_cffi Is

**v0.15.1b1** — Python FFI bindings for libcurl with browser impersonation.
MIT license. Pure C FFI (no Go daemon, no subprocess). ~3,700 lines of Python.

**Core capability**: Makes HTTP requests that are **indistinguishable from real browsers**
at the TLS/HTTP2/TCP fingerprint level. This is the layer below what Patchright handles.

## API Surface (What We'd Use)

### Session API (Primary)

```python
from curl_cffi.requests import AsyncSession, Session

# Sync — simple request
r = curl_cffi.get("https://example.com", impersonate="chrome146")

# Sync — session (reuses connection + cookies)
with Session(impersonate="chrome146") as s:
    r = s.get("https://example.com")
    r2 = s.post("https://example.com/api", json={"key": "val"})

# Async — session (our primary use case)
async with AsyncSession(impersonate="chrome146") as s:
    r = await s.get("https://example.com")
    r = await s.post("https://example.com/api", json=data)
```

### Impersonation Targets (53 built-in)

| Browser | Versions | Default |
|---------|----------|---------|
| Chrome | 99–146 | `chrome146` |
| Edge | 99–101 | `edge101` |
| Safari | 15.3–26.0.1 | `safari2601` |
| Firefox | 133–147 | `firefox147` |
| Tor | 14.5 | `tor145` |
| Chrome Android | 99, 131 | `chrome131_android` |

### Fingerprint Customization (Advanced)

```python
# JA3 fingerprint string
r = s.get(url, ja3="771,4866-4867-...,0-23-65281-...")

# Akamai fingerprint
r = s.get(url, akamai="4:16777216|16711681|0|m,p,a,s")

# Perk fingerprint
r = s.get(url, perk="...")

# Extra fine-tuning
r = s.get(url, extra_fp={
    "tls_signature_algorithms": ["ecdsa_secp256r1_sha256", ...],
    "tls_grease": True,
    "tls_permute_extensions": True,
    "tls_cert_compression": "brotli",
    "http2_stream_weight": 256,
    "http2_stream_exclusive": 1,
})
```

### Response Object

```python
r.status_code      # int
r.headers          # Headers dict-like
r.content          # bytes
r.text             # str (auto-decoded)
r.json()           # parsed JSON
r.url              # final URL (after redirects)
r.cookies          # Cookies object
r.elapsed          # timedelta
r.ok               # 200 <= status < 400
r.primary_ip       # server IP
r.http_version     # int (0x0200 = HTTP/2)
```

### Proxy Support

```python
# Per-request proxy
r = s.get(url, proxy="http://user:pass@proxy:8080")

# Session-level proxy
s = Session(proxy="socks5://proxy:1080")

# Protocol-specific proxies
s = Session(proxies={"http": "http://p1:8080", "https": "socks5://p2:1080"})
```

### Streaming & WebSockets

```python
# Streaming
r = await s.get(url, stream=True)
async for chunk in r.aiter_content():
    process(chunk)

# WebSocket
ws = await s.ws_connect("wss://echo.ws.org")
await ws.send(b"hello")
msg = await ws.recv()
```

### Retry

```python
from curl_cffi.requests import RetryStrategy

s = Session(retry=RetryStrategy(count=3, delay=1.0, jitter=0.5, backoff="exponential"))
```

## Key Properties

| Property | Value |
|----------|-------|
| TLS fingerprint | Spoofs JA3/JA4 at libcurl level (BoringSSL) |
| HTTP/2 fingerprint | Settings, window update, pseudo-header order |
| HTTP/3 (QUIC) | Supported via `http_version="v3"` for Chrome 145+ |
| Cookie jar | Automatic, persistent across requests |
| Connection reuse | Yes (curl multi handle pool) |
| Thread safety | Session is thread-safe, uses thread-local curl handles |
| Async | Full async via `AsyncSession` with `AsyncCurl` event loop |
| Performance | C FFI — near-native speed |
| Dependencies | `cffi>=2.0.0`, `certifi>=2024.2.2` |
| Size | ~15MB (includes compiled libcurl + BoringSSL) |

## What This Gives Us vs. Current State

### Current Stealth Stack

```
Layer 1: Patchright (forked Playwright)      → browser-level stealth
         - Removes webdriver flag
         - Patches navigator properties
         - Uses real Chrome binary

Layer 2: CDP Fetch.requestPaused             → JS injection
         - Injects stealth scripts into HTML
         - Undetectable (modifies response body)
         - Falls back to addScriptToEvaluateOnNewDocument

Layer 3: httpmorph (imported but optional)    → network-level stealth
         - Falls back to urllib.request (NO TLS SPOOFING)
         - Proxy escalation logic exists but network
           fingerprint is Python/urllib → INSTANTLY DETECTED

Layer 4: Proxy rotation                       → IP-level stealth
         - Direct → Residential → Premium Residential → Datacenter TLS
```

**The gap**: Layer 3 (network stealth) doesn't work. `httpmorph` is imported
but probably not installed. The fallback (`urllib.request`) has a Python TLS
fingerprint that any anti-bot system detects immediately.

### What curl_cffi Fixes

```
Layer 3 (REPLACED): curl_cffi AsyncSession   → network-level stealth
         - TLS fingerprint: matches Chrome 146 exactly
         - HTTP/2 settings: matches real browser
         - Connection reuse: like a real browser
         - Cookie persistence: across requests
         - Proxy support: all protocols
```

Anti-bot systems check the TLS fingerprint of **outgoing HTTP requests**
(separate from the browser's TLS). When the agent needs to:
- Pre-fetch a page to check for CAPTCHAs
- Make API calls that don't go through the browser
- Verify a URL before navigating
- Collect intelligence about a target site

...those requests currently use `urllib.request` (Python fingerprint = detected).
With curl_cffi, they'd use Chrome 146's fingerprint = undetectable.

## Integration Points

### Point 1: StealthManager._do_http_request() (Direct Replacement)

**Current** (line ~166 of `stealth/manager.py`):
```python
async def _do_http_request(self, config, proxy_url, tier, start):
    try:
        from httpmorph import Client  # ← not installed
        client = Client(proxy=proxy_url)
        resp = client.request(...)
    except ImportError:
        import urllib.request  # ← NO TLS SPOOFING
        ...
```

**With curl_cffi**:
```python
async def _do_http_request(self, config, proxy_url, tier, start):
    from curl_cffi.requests import AsyncSession
    async with AsyncSession(
        impersonate=self._config.chrome_version_profile,
        proxy=proxy_url,
    ) as s:
        resp = await s.request(config.method, config.url, ...)
        return HTTPMorphResponse(
            status_code=resp.status_code,
            headers=dict(resp.headers),
            body=resp.content,
            url=resp.url,
            timing_ms=(time.monotonic() - start) * 1000,
            proxy_tier_used=tier,
        )
```

### Point 2: StealthConfig Updates

```python
@dataclass(frozen=True)
class StealthConfig:
    ...
    # Replace:
    httpmorph_enabled: bool = True
    # With:
    curl_impersonate_target: str = "chrome146"  # curl_cffi browser target
    curl_impersonate_extra_fp: Optional[dict] = None  # ExtraFingerprints as dict
```

### Point 3: Diagnostics Enhancement

curl_cffi can verify its own TLS fingerprint:
```python
r = await session.get("https://tls.browserleaks.com/json")
ja4 = r.json().get("ja4_hash")  # Verify it matches expected Chrome hash
```

Add to `run_diagnostics()`:
- TLS JA4 check via curl_cffi (compare against known-good Chrome hash)
- HTTP/2 settings frame check

## What curl_cffi Does NOT Do

1. **Browser automation** — It's an HTTP client, not a browser driver.
   Patchright handles DOM interaction. curl_cffi handles network fingerprinting.

2. **JavaScript execution** — No JS engine. Can't render pages.
   Pure HTTP request/response.

3. **Replace Patchright** — These are complementary, not competing:
   - Patchright = browser automation (DOM, screenshots, AX tree)
   - curl_cffi = network stealth (TLS, HTTP/2, cookies)

4. **Desktop automation** — No window management, mouse, keyboard.
   That's what `SurfaceAdapter` + `pyautogui` + `win32gui` handle.

## Dependency Assessment

```
curl_cffi 0.15.1b1
├── cffi >= 2.0.0        # FFI bridge (pure Python + C)
├── certifi >= 2024.2.2  # CA bundle
└── compiled libcurl     # Bundled in wheel (~15MB)
    └── BoringSSL        # TLS implementation (bundled)
```

No heavy ML deps. No external daemons. Pure Python + compiled C library.
The wheel is ~15MB. Install time < 10 seconds.

## Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| BETA version (0.15.1b1) | Medium | Pin version; API has been stable across 0.x |
| BoringSSL bundled | Low | Same engine Chrome uses |
| FFI overhead | Low | C-level performance, minimal Python overhead |
| Detection evolution | Ongoing | curl_cffi updates fingerprints regularly |
| GPL concern (libcurl) | None | curl_cffi uses MIT-licensed BoringSSL, not OpenSSL |

## Implementation Effort

| Task | Lines | Effort |
|------|-------|--------|
| Replace `_do_http_request()` with curl_cffi | ~30 | 1h |
| Update `StealthConfig` types | ~15 | 30m |
| Add TLS JA4 diagnostic check | ~30 | 1h |
| Add `StealthConfig.chrome_version_profile` → curl_cffi target mapping | ~20 | 30m |
| Tests (mocked) | ~100 | 2h |
| Integration test (real TLS check) | ~30 | 1h |
| Update `pyproject.toml` | ~3 | 5m |
| **Total** | **~230** | **~6h** |
