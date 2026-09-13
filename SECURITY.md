# Security — Delhi NCR AQI Forecasting System

## Threat Model

| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|------------|
| API key exposure in repo | High | Critical | `.env` in `.gitignore`; `.env.example` has zero real values |
| Unauthorized data ingestion | Medium | High | `X-API-Key` required on all POST endpoints; placeholder key fails closed |
| Secret recovery by response timing | Low | High | `secrets.compare_digest`, not `==` |
| DDoS / abusive scraping | Medium | Medium | `slowapi` rate limiting (20–120 req/min per IP, in-memory) |
| Cross-site injection via CORS | Low | Medium | CORS restricted to `ALLOWED_ORIGINS` env var |
| Container breakout via root | Low | High | Multi-stage Docker; non-root `appuser` at runtime |
| Clickjacking | Low | Low | `X-Frame-Options: DENY` header |
| MIME sniffing | Low | Low | `X-Content-Type-Options: nosniff` |
| Coordinate injection (bbox bypass) | Medium | Medium | Pydantic `DelhiBBox` model with `ge`/`le` validators |
| Dependency supply chain attack | Medium | High | Pinned versions in `requirements.txt`; see scanning below |

The rate limiter's storage is in-process, so its counters reset on restart and are
not shared between workers. That is one of the reasons the container runs
`--workers 1` (the other is the response cache). It is a courtesy limit against
accidental hammering, not a defence against a distributed attacker — put a proxy
in front of it if you need one.

---

## API Authentication

### Read endpoints (GET)
Public — no authentication required. Protected by rate limiting only.

### Mutation endpoints (POST `/api/v1/ingest/observation`)
Require `X-API-Key` HTTP header:

```http
POST /api/v1/ingest/observation
X-API-Key: <APP_API_KEY from .env>
Content-Type: application/json
```

Scope note: this endpoint validates the payload and returns `202 Accepted`. There
is no database behind it, so the key is not currently guarding a data store — it
guards a validation endpoint. Treat that as the honest description until
persistence exists.

The key is validated in `backend/app/core/security.py` via FastAPI's `Security()` dependency.

Two properties of that check are deliberate:

**It fails closed on a placeholder.** `APP_API_KEY` ships as `change-me` in
`.env.example`. If it is still that value (or empty) when a request arrives, the
endpoint returns `503 Service Unavailable` with "Ingestion is disabled" rather
than comparing against it. Otherwise anyone who had read `.env.example` — which is
committed — would hold a valid credential on any deployment that forgot to set
the variable.

**The comparison is constant-time.** `secrets.compare_digest`, not `==`. A plain
string comparison returns as soon as it finds a differing byte, so the time to
reject `a...`, `b...`, `c...` differs measurably by whether the first character
was right. Repeated over 32 characters that recovers the whole secret. This is
a small risk on a hackathon deployment and a free fix.

Invalid or missing keys return `403 Forbidden` with no detail about which part
failed.

**Key generation** (production):
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## Secure HTTP Headers

Applied globally via middleware in `backend/app/main.py`:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | Prevent MIME type sniffing |
| `X-Frame-Options` | `DENY` | Prevent clickjacking |
| `X-XSS-Protection` | `1; mode=block` | Legacy XSS filter |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limit referrer leakage |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; …` | Restrict resource loading |
| `Strict-Transport-Security` | `max-age=63072000` | Force HTTPS (2 years) |

### The documentation-route CSP exception

`/docs`, `/redoc` and `/docs/oauth2-redirect` get a different, looser
`Content-Security-Policy` — the constant `DOCS_CSP` in `security.py`. This is not
an oversight, and it is worth knowing about before you tighten anything:

FastAPI serves Swagger UI and ReDoc as thin HTML shells that pull their
JavaScript and CSS from `cdn.jsdelivr.net`. Under `script-src 'self'` the browser
blocks that bundle and `/docs` renders as a permanently blank page — while
`README.md` and `API.md` both tell the reader to open it. So the middleware widens
`script-src`, `style-src`, `font-src` and `img-src` to the specific CDN hosts those
two pages need, on those three paths only. Every API route keeps the strict
policy, and `connect-src` stays `'self'` everywhere, so the relaxed pages still
cannot exfiltrate to a third party.

If you would rather not allow a CDN at all, the alternative is to vendor the
Swagger UI assets and mount them with `StaticFiles`, then set
`docs_url=None` and register a custom docs route. That removes the exception
entirely at the cost of carrying ~1 MB of JS in the repo.

---

## CORS Configuration

CORS is restricted to origins listed in `ALLOWED_ORIGINS` (comma-separated, from `.env`).

**Development** (`.env`):
```
ALLOWED_ORIGINS=http://localhost:8501
```

**Production** (`.env`):
```
ALLOWED_ORIGINS=https://your-dashboard.your-domain.com
```

Allowed methods: `GET`, `POST` only. `PUT`, `DELETE`, `PATCH` are not exposed.

---

## Input Validation

All query parameters and POST bodies are validated by Pydantic models with strict constraints:

- **`DelhiBBox`**: Latitude constrained to 28.0–29.0°N, longitude to 76.5–77.8°E. Extra fields forbidden.
- **`StationObservation`**: All concentration fields have physical upper bounds. `station_id` is length-limited. `extra = "forbid"` rejects unknown fields.
- FastAPI automatically returns `422 Unprocessable Entity` for any validation failure, with no sensitive data in the error body.

---

## Non-Root Container Deployment

The backend `Dockerfile.backend` uses a multi-stage build:

**Stage 1 (builder)**: installs packages as root (required for pip compilation)  
**Stage 2 (runtime)**: copies only the installed packages, creates `appuser`, runs as `appuser`

```dockerfile
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
```

Verify:
```bash
docker-compose exec backend whoami
# appuser
```

The frontend uses the official `python:3.11-slim` image — no modifications needed as Streamlit runs on a high port (8501) which does not require root.

---

## Secrets Management

1. **Never commit `.env`** — it is in `.gitignore`
2. **Use `.env.example`** as the template — it has no real values
3. In production, inject secrets via your orchestrator (Kubernetes Secrets, AWS Secrets Manager, etc.) rather than `.env` files on disk
4. **Rotate `APP_API_KEY`** if it is ever exposed — update `.env` and restart containers

Three secrets exist, with different blast radii:

| Variable | What it is | If leaked |
|---|---|---|
| `APP_API_KEY` | Your own shared secret for the ingest endpoint | Rotate. Anyone holding it can POST observations |
| `OPENAQ_API_KEY` | Free read-only upstream key | Low impact — rotate at leisure via the OpenAQ dashboard |
| `FIRMS_API_KEY` | Free NASA FIRMS MAP_KEY | Low impact — read-only, quota-limited |

`.env` is resolved from the repository root by absolute path (`config.py` derives
it from `__file__`, not from the working directory), so there is no scenario where
a different `.env` is silently picked up because the process was launched from
another folder.

---

## Dependency Scanning Checklist

Run before each production deploy:

```bash
# 1. Check for known vulnerabilities
pip install pip-audit
pip-audit -r requirements.txt

# 2. Check for outdated packages
pip list --outdated

# 3. Verify pinned hashes (optional, for high-security environments)
pip install pip-tools
pip-compile --generate-hashes requirements.txt -o requirements.lock
```

**CI recommendation**: Add `pip-audit` as a GitHub Actions step on every PR.

---

## Production Hardening Checklist

- [ ] Set `APP_ENV=production` and `APP_DEBUG=false`
- [ ] Generate a strong `APP_API_KEY` (≥ 32 random bytes) — ingestion returns `503` while it is still `change-me`
- [ ] Set `ALLOWED_ORIGINS` to your exact frontend URL (no wildcards)
- [ ] Put the backend behind a TLS-terminating reverse proxy (nginx/Caddy/ALB)
- [ ] Enable `HSTS` at the proxy level (already set in response headers)
- [ ] Move rate limiting to the proxy — the built-in limiter is per-process and in-memory
- [ ] Run `pip-audit` in CI on every pull request
- [ ] Restrict Docker socket access (do not mount it in containers)
- [ ] Set resource limits in docker-compose (`mem_limit`, `cpus`)
- [ ] Enable Docker content trust: `DOCKER_CONTENT_TRUST=1`
- [ ] Decide on the `/docs` CSP exception: keep the CDN allowance, vendor the assets, or disable `/docs` in production
