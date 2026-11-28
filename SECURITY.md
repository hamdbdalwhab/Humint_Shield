# HUMINT Shield — Security Architecture

This document lists the security controls implemented in the platform, the
threat model they address, and the incident-response procedure. It describes
the code in this repository; deployment-specific controls (TLS certificates,
host firewall, secret manager) are documented in [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 1. Implemented controls

### 1.1 Authentication & session management

| Control | Implementation | Location |
|---|---|---|
| Password hashing | bcrypt, cost 12 (configurable), 72-byte pre-hash for long inputs | `app/security.py` |
| Password policy | ≥ 8 chars, upper + lower + digit + special, enforced in Pydantic and at the endpoint | `app/schemas/password_policy.py` |
| Account lockout | 5 consecutive failures → 15-minute lock (HTTP 423, `Retry-After`) | `app/api/v1/auth.py` |
| Username enumeration resistance | bcrypt verified against a dummy hash for unknown accounts | `auth.py::_dummy_password_hash` |
| Session revocation (bulk) | `users.token_version` echoed in the JWT `ver` claim; logout/password change increments it | `security.py`, `deps.py` |
| Session revocation (per token) | `token_revocations` table keyed by `jti`, checked on every authenticated request | `app/models/audit.py`, `deps.py` |
| Token lifetime | Access 60 min, refresh 7 days (configurable) | `app/config.py` |
| Self-service password change | `POST /api/v1/auth/change-password`, rotates tokens + records revocation | `auth.py` |

### 1.2 Authorization & tenant isolation

- Every organization-scoped route resolves the organization through
  `get_organization_or_404`, which returns **403** to members of another tenant
  and **404** for unknown ids.
- Role-based access (`admin`, `manager`, `viewer`) via `require_roles`.
  Destructive operations are admin-only (delete employee/campaign, invite user,
  containment trigger, security policy changes).
- Campaign/employee lookups re-verify `organization_id` on the row itself, so a
  guessed UUID cannot cross tenants.
- Decrypted PII (`email`, `phone`) is exposed through a dedicated **admin-only**
  endpoint (`GET .../employees/{id}/sensitive`).

### 1.3 Data protection

| Data | Protection |
|---|---|
| Passwords | bcrypt hash, never logged or returned |
| Employee `phone` | AES-256-GCM via `EncryptedString` (legacy column) **and** `phone_encrypted` (BYTEA) |
| Employee `email` | AES-256-GCM in `email_encrypted` (BYTEA); plaintext kept for the unique index/search |
| Captured form payloads | AES-256-GCM (`submitted_payload_encrypted`) |
| In transit | TLS 1.2/1.3 at the edge, HSTS, same-origin CSP |
| Backups | `pg_dump`/SQLite copy, filesystem mode 0600, 30-day retention; encrypt before off-host storage |

Encryption keys come from `ENCRYPTION_KEY`; production startup refuses
generated or short keys (`config.py::_enforce_production_secrets`).

### 1.4 Auditing & forensics

- `audit_logs` records **who / what / when / from where** with JSON before and
  after snapshots for: employee create/delete, campaign update/delete,
  organization settings update, operator invite.
- Audit rows are written in the same transaction as the mutation.
- `token_revocations` records logout/password-change revocations with a reason.
- Structured JSON request logs include a correlation id (`X-Request-ID`).
- Interaction ledger records every simulated engagement event with timestamps,
  IP and user agent for the training report.

### 1.5 Input handling

- Pydantic v2 schemas validate every request body; unknown/invalid data is a 422.
- Plain-text fields (names, job titles, campaign/template names and subjects)
  have HTML stripped and are rejected if they contain `<script>`, `<iframe>`,
  `<object>`, `<embed>`, `<svg>`, `javascript:`, `vbscript:`, `data:text/html`
  or inline `onerror=`/`onclick=` handlers.
- HTML template bodies are compiled and neutralised by the template pipeline
  (scripts, handlers and `javascript:` URLs removed) rather than trusted.
- Uploads: logos are re-encoded through Pillow (SVG rejected), size and pixel
  caps enforced; CSV import capped at 5 MB with header validation.
- SQL access goes through SQLAlchemy with bound parameters.

### 1.6 Availability & abuse resistance

- Application-layer sliding-window rate limits (Redis, in-memory fallback):
  auth endpoints and QR probe/submit are stricter.
- Network-layer limits at nginx: 5 r/min/IP login, 60 r/min/IP API.
- Request body limits, pagination caps (`per_page ≤ 200`), CSV/logo size caps.
- Redis outage degrades to per-process limits and retries the connection.

### 1.7 Operational controls

- `/metrics` disabled by default; when enabled it is restricted by IP allow-list
  and HTTP Basic Auth at the edge.
- Production secrets required at startup; CORS dev wildcards disabled in
  production; proxy headers trusted only when configured.
- `scripts/backup_db.sh` with 30-day retention; restore drill documented.
- Environment separation via `APP_ENV` overlays (`.env.development`,
  `.env.production`); real secrets only in the untracked `.env`.

---

## 2. Threat model

### 2.1 Assets

1. Employee PII (name, corporate e-mail, phone, department).
2. Captured simulation credentials and behavioural evidence.
3. Campaign definitions, templates and results.
4. Operator accounts and session tokens.
5. Sender/LLM provider credentials.

### 2.2 Adversaries

| Adversary | Capability | Primary controls |
|---|---|---|
| External unauthenticated attacker | Internet access, scanning, credential stuffing | TLS, nginx rate limits, lockout, generic auth errors, minimal attack surface |
| Malicious/curious insider (viewer) | Valid low-privilege account | RBAC, tenant scoping, admin-only PII route, audit trail |
| Compromised operator session | Stolen bearer token | Short access lifetime, `token_version`, `jti` revocation, logout-everywhere |
| Database thief (backup/disk) | Offline access to storage | AES-256-GCM columns, bcrypt hashes, encrypted backups |
| Phishing of the platform itself | Credential capture | Lockout, rate limits, CSP, HSTS, no third-party scripts |
| Cross-tenant attacker | Guessed UUIDs | Organization checks on every scoped query, 404 vs 403 semantics |
| Supply-chain/insider developer | Code access | Single audit choke point, no plaintext secrets in repo, production config gate |

### 2.3 Trust boundaries

```
Internet ──TLS──► nginx edge (rate limit, headers, metrics gate)
                        │ HTTP (private network)
                        ▼
                 FastAPI (authn/authz, validation, audit)
                    │                 │
             PostgreSQL          Redis / Celery
```

- The edge is the only public listener; database/Redis ports are not published.
- The backend trusts `X-Forwarded-*` **only** when `TRUST_PROXY_HEADERS=true`.
- Email/WhatsApp/SMS/voice provider responses are untrusted input and are
  parsed defensively.

### 2.4 Out of scope / residual risk

- A host-level root compromise (can read process memory and keys).
- Availability attacks at volumes beyond the ISP/Cloudflare tier.
- Third-party provider breaches (Brevo, TextBee, WA-AKG, IllyVoIP, LLM).
- Legal/consent failures by the operating organization: the platform is a
  training tool and must be used only with written authorization and employee
  notice. Simulated credential pages warn recipients that it is a simulation.

---

## 3. Incident response

### 3.1 Severity

| Level | Example | First response |
|---|---|---|
| SEV-1 | Confirmed tenant data leak, admin takeover, key exposure | 15 min |
| SEV-2 | Suspicious admin activity, repeated lockouts, provider key abuse | 1 hour |
| SEV-3 | Isolated 5xx, failed backup, certificate expiry | Next business day |

### 3.2 Procedure

1. **Detect & declare** — alert from `/metrics`, 429/423 spikes, backup failure,
   or a report to `security@<org>`. Open an incident channel and assign an IC.
2. **Contain**
   - Revoke sessions: `UPDATE users SET token_version = token_version + 1 WHERE id = '<id>';`
   - Disable the account: `UPDATE users SET is_active = false WHERE id = '<id>';`
   - Rotate `SECRET_KEY` (invalidates all tokens), then provider keys.
   - If the encryption key is exposed: rotate `ENCRYPTION_KEY`, re-run the
     backfill migration for `human_assets`, and re-encrypt captured payloads.
   - Block the source at the edge/firewall (`fail2ban`, Cloudflare rule).
3. **Eradicate** — patch the defect, add a regression test, redeploy.
4. **Recover** — restore from the last verified backup if data integrity is in
   doubt; verify `/healthz`, login, and a read/write path before announcing.
5. **Notify** — follow the organization's legal/DPO obligations (e.g. GDPR
   72-hour notification) and contractual customer notice.
6. **Learn** — write a post-incident review within 5 business days: timeline,
   root cause, blast radius, control gap, owner and due date.

### 3.3 Evidence handling

- Preserve `audit_logs`, `token_revocations`, structured request logs and the
  relevant backup. Record SHA-256 hashes before copying.
- Do not edit or delete evidence; export a read-only copy to the incident
  workspace. Personal data in evidence is handled under the retention policy.

### 3.4 Recovery objectives

| Objective | Target |
|---|---|
| RPO (backups) | ≤ 24 h (daily dump) |
| RTO (restore) | ≤ 2 h on staging-verified dump |
| Session revocation propagation | immediate (next request) |
| Key rotation window | ≤ 1 h for `SECRET_KEY`, ≤ 4 h for `ENCRYPTION_KEY` |

---

## 4. Security testing

- `backend/tests/` covers authz/tenant isolation, lockout, revocation, audit
  logging, encryption round-trips and sanitisation; the suite enforces an 80%
  coverage floor.
- Recommended pre-release checks: dependency audit (`pip-audit`, `npm audit`),
  `ruff`/`tsc`, container image scan (Trivy), and a restore drill.

## 5. Reporting a vulnerability

Contact the deploying organization's security team through its private channel.
Do not open a public issue containing exploit details or employee data.
