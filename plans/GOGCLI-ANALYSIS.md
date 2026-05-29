# gogcli Reference Analysis

> **Repo:** `C:\Next AI\ref\gogcli-main`
> **What:** Go CLI for 18+ Google Workspace APIs (Gmail, Calendar, Drive, Docs, Sheets, Tasks, etc.)
> **By:** steipete (Peter Steinberger)
> **License:** Apache-2.0
> **Size:** ~500+ Go files in `internal/cmd/`, ~30 API client files in `internal/googleapi/`

---

## 1. Agent Integration Patterns

### Exit Codes (Machine-Readable Status)

gogcli defines **11 stable exit codes** that agents can branch on without parsing stderr:

| Code | Name | Meaning |
|------|------|---------|
| 0 | `ok` | Success |
| 1 | `error` | Generic failure |
| 2 | `usage` | Parse/usage error |
| 3 | `empty_results` | Valid query, no results |
| 4 | `auth_required` | Need OAuth/credentials |
| 5 | `not_found` | Resource doesn't exist |
| 6 | `permission_denied` | Insufficient scope/role |
| 7 | `rate_limited` | 429 / quota exceeded |
| 8 | `retryable` | Network timeout, 5xx |
| 10 | `config` | Missing config/credentials |
| 130 | `cancelled` | SIGINT / Ctrl-C |

**File:** `internal/cmd/exit_codes.go` — `stableExitCode()` wraps any error into an `ExitError{Code, Err}`.

### Machine-Readable Schema

`gog schema` (aliases: `help-json`, `helpjson`) emits a **full CLI schema** as JSON:

```json
{
  "schema_version": 1,
  "build": "v1.x",
  "command": {
    "type": "application",
    "name": "gog",
    "subcommands": [...],
    "flags": [...],
    "requirements": [...]
  }
}
```

Agents can discover available commands, flags, types, defaults, and env vars **without parsing --help text**.

### Desire Paths (Agent-Friendly Shortcuts)

Top-level shortcuts map to nested commands:
- `gog send` → `gog gmail send`
- `gog ls` → `gog drive ls`
- `gog search` → `gog drive search`
- `gog me` → `gog people me`

Plus `--fields` is automatically rewritten to `--select` for agents that guess wrong flag names.

---

## 2. Error Taxonomy

### Typed Error Hierarchy

```
ExitError (base, carries exit code)
├── AuthRequiredError    (service, email, client, cause)
├── RateLimitError       (retryAfter, retries)
├── CircuitBreakerError  (too many recent failures)
├── QuotaExceededError   (resource)
├── NotFoundError        (resource, id)
└── PermissionDeniedError(resource, action)
```

Each error has:
- Structured fields (not just strings)
- `Unwrap()` for error chain
- `Is*Error()` type guards

### Circuit Breaker

- **Threshold:** 5 consecutive failures → open circuit
- **Reset:** 30s cooldown, then half-open (one probe)
- **State:** `closed` | `open`
- **File:** `internal/googleapi/circuitbreaker.go`

### Retry Transport

`RetryTransport` wraps `http.RoundTripper`:
- **429:** Max 3 retries, exponential backoff (1s, 2s, 4s) + jitter
- **5xx:** Max 1 retry, 1s delay
- **4xx (non-429):** No retry
- Respects `Retry-After` header (seconds or HTTP-date)
- Context-aware: interrupted sleeps propagate `ctx.Err()`

---

## 3. Safety Patterns

### Dry Run (`--dry-run`, `-n`)

Every mutating command checks `flags.DryRun` **before** any API call:

```go
func dryRunExit(ctx, flags, op, request) error {
    if !flags.DryRun { return nil }
    // Print intended operation + request as JSON
    return &ExitError{Code: 0}  // Success, no mutation
}
```

Three output modes: JSON (`{dry_run, op, request}`), plain TSV, human text.

### Confirmation for Destructive Actions

```go
confirmDestructive(ctx, flags, action) error
```

Flow:
1. Check dry-run first → exit if dry
2. `--force` / `-y` → skip prompt
3. `--no-input` or non-TTY → refuse (error, not prompt)
4. TTY → `[y/N]` prompt

### Command Guards (Sandboxing)

```bash
--enable-commands calendar,tasks          # Allowlist
--disable-commands gmail.send,gmail.drafts.send  # Denylist
--gmail-no-send                           # Block all Gmail sends
```

Env vars: `GOG_ENABLE_COMMANDS`, `GOG_DISABLE_COMMANDS`, `GOG_GMAIL_NO_SEND`

Matching uses dot-path prefix: `gmail.send` blocks `gmail send` but not `gmail search`.

### Config-Level Send Guard

```json5
{
  gmail_no_send: true,
  no_send_accounts: { "agent@example.com": true }
}
```

---

## 4. Auth & Secrets

### Multi-Layer Auth

| Method | Use Case | Priority |
|--------|----------|----------|
| OAuth refresh token | Human users | Default |
| Service account (domain-wide delegation) | Workspace | Overrides OAuth |
| ADC (Application Default Credentials) | GKE/CI | `GOG_AUTH_MODE=adc` |
| Direct access token | CI/headless | `GOG_ACCESS_TOKEN` |

### Secret Storage

- **macOS:** Keychain (via `99designs/keyring`)
- **Linux:** Secret Service / GNOME Keyring
- **Windows:** Credential Manager
- **Fallback:** Encrypted on-disk (`GOG_KEYRING_BACKEND=file` + `GOG_KEYRING_PASSWORD`)
- **Timeout:** Keychain operations bounded to prevent hangs

### Multiple OAuth Clients

Named clients with domain auto-selection:
```json5
{
  account_clients: { "you@company.com": "work" },
  client_domains: { "example.com": "work" }
}
```

Token keys are per-client: `token:<client>:<email>`.

---

## 5. Output Formatting

### Three Modes

| Mode | Flag | Use |
|------|------|-----|
| Human | (default) | Colored tables, progress on stderr |
| JSON | `--json` / `-j` | Structured data on stdout |
| Plain | `--plain` / `-p` | TSV on stdout, no colors |

### JSON Transform Pipeline

```bash
--results-only          # Strip envelope, emit only primary data
--select id,summary     # Project to specific fields (dot paths supported)
```

`outfmt.WriteJSON()` applies transforms:
1. `ResultsOnly` → unwrap envelope (drops `nextPageToken`, etc.)
2. `Select` → project each item to requested fields

### Context-Based Formatting

Output mode stored in `context.Context`:
```go
ctx = outfmt.WithMode(ctx, mode)
// Later:
if outfmt.IsJSON(ctx) { ... }
```

---

## 6. Config System

- **Format:** JSON5 (supports comments, trailing commas)
- **Path:** `~/Library/Application Support/gogcli/config.json` (macOS), `%AppData%/gogcli/config.json` (Win)
- **File locking:** `config.lock` with 2s timeout, PID-based
- **Account aliases:** `gog auth alias set work work@company.com`
- **Calendar aliases:** `gog config set calendar_aliases '{"work": "work@company.com"}'`
- **Timezone:** `gog config set timezone UTC`

---

## 7. What Desktop-Agent Should Adopt

### High Priority (Directly Applicable)

| Pattern | gogcli Implementation | Desktop-Agent Equivalent |
|---------|----------------------|-------------------------|
| **Stable exit/status codes** | 11 typed codes, `ExitError` | Already have `ResultStatus` enum — add `RATE_LIMITED`, `RETRYABLE`, `EMPTY_RESULTS`, `CONFIG_ERROR` |
| **Machine-readable schema** | `gog schema` JSON output | Add `DesktopAgent.schema()` returning capability manifest as structured JSON |
| **Dry-run everywhere** | `dryRunExit()` before every mutation | Already have `dry_run` in context — ensure EVERY mutating action checks it first |
| **Confirmation for destructive actions** | `confirmDestructive()` with force/no-input | Add to policy bridge: `sensitive` actions require confirmation unless `--force` |
| **Command guards** | `--enable-commands` / `--disable-commands` | Map to `PolicyBridge` permission filtering |
| **Circuit breaker** | 5 failures → 30s cooldown | Add to `RecoveryBridge` — already has `max_attempts`, add cooldown timer |
| **Typed error chain** | `AuthRequiredError`, `RateLimitError`, etc. | Extend `ActionError.code` with canonical codes (already have 6) |
| **Retry with backoff + jitter** | Exponential + `Retry-After` header | Add to retry logic in `RecoveryBridge` |

### Medium Priority (Good Patterns)

| Pattern | What to Take |
|---------|-------------|
| **JSON transform pipeline** | `--select` field projection for ActionResult output |
| **Context-based formatting** | Pass output mode through execution context |
| **File-based config** | JSON5 config at `AIOS_HOME/capabilities/desktop_agent/config.json5` |
| **Account aliasing** | Surface alias mapping (e.g. "chrome" → app ID) |
| **Auto JSON on pipe** | When stdout is piped, default to structured output |

### Lower Priority (Nice to Have)

| Pattern | What to Take |
|---------|-------------|
| **Encrypted backup** | Age-encrypted action memory export |
| **Email tracking** | N/A for desktop |
| **Service account auth** | AI-OS handles auth for us |
| **Multiple OAuth clients** | AI-OS handles auth for us |

### Anti-Patterns to Avoid

| gogcli Pattern | Why Not for Desktop-Agent |
|----------------|--------------------------|
| CLI-first design | Desktop-Agent is a library/capability, not a CLI |
| Google-specific auth | AI-OS provides auth |
| Kong CLI framework | Python, not Go |
| Per-command file structure | Desktop-Agent uses class-based modules |

---

## Key Takeaway

gogcli's strongest contribution to Desktop-Agent is the **safety + observability stack**:
1. Typed exit codes → structured error taxonomy
2. Dry-run before every mutation → `PolicyBridge` integration
3. Circuit breaker → bounded recovery with cooldown
4. Command guards → permission-based action filtering
5. Machine-readable schema → self-describing capabilities

These are all **cross-cutting concerns** that gogcli solved well and that map directly to Desktop-Agent's bridge architecture.
