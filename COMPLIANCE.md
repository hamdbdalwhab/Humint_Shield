# HUMINT Shield — Compliance Mapping & Data Handling

This document maps the platform's implemented controls to **ISO/IEC 27001:2022**
(Annex A) and **NIST SP 800-53 Rev. 5**, and states the data-handling rules the
deploying organization must operate under. Mappings describe how the software
supports a control; they are not a certification. Certification requires an
audit of the whole organization, its processes and its hosting environment.

---

## 1. Scope

In scope: the HUMINT Shield application (FastAPI backend, React dashboard,
Celery workers), its PostgreSQL database, Redis, nginx edge, and the delivered
Docker Compose deployment.

Out of scope: the host OS, cloud provider infrastructure, identity provider,
corporate network, and the operating organization's HR/legal processes.

---

## 2. ISO/IEC 27001:2022 Annex A mapping

### 2.1 Organizational controls (A.5)

| Control | Requirement | Implementation |
|---|---|---|
| A.5.1 | Policies for information security | `SECURITY.md`, this document |
| A.5.10 | Acceptable use of information and assets | Simulation-only scope, authorization notice on landing pages |
| A.5.12 | Classification of information | PII columns encrypted; audit/evidence treated as confidential |
| A.5.15 | Access control | RBAC (`admin`/`manager`/`viewer`), admin-only destructive routes |
| A.5.17 | Authentication information | bcrypt hashes, password policy, lockout, no plaintext secrets in repo |
| A.5.23 | Cloud service security | Secret-free templates, production config gate |
| A.5.28 | Collection of evidence | `audit_logs`, `token_revocations`, interaction ledger |
| A.5.33 | Protection of records | Transactional audit trail, 30-day backup retention |
| A.5.34 | Privacy and PII protection | Field-level encryption, admin-only decryption route, retention policy |

### 2.2 People controls (A.6)

| Control | Requirement | Implementation |
|---|---|---|
| A.6.3 | Awareness and training | The platform's purpose; LMS modules and micro-learning |
| A.6.5 | Responsibilities after termination | Admin can disable an account (`is_active`) and revoke sessions |
| A.6.8 | Event reporting | Security reporting channel in `SECURITY.md` §5, report inbox |

### 2.3 Physical controls (A.7)

Physical controls are inherited from the hosting provider. The software
supports them through encrypted storage and encrypted backups.

### 2.4 Technological controls (A.8)

| Control | Requirement | Implementation |
|---|---|---|
| A.8.1 | User endpoint devices | Device fingerprint evidence, USB-drop awareness |
| A.8.2 | Privileged access rights | Admin-only: delete, invite, containment, security policy |
| A.8.3 | Information access restriction | Tenant scoping, `get_organization_or_404`, role checks |
| A.8.5 | Secure authentication | bcrypt, JWT with `ver`+`jti`, lockout, rotation |
| A.8.7 | Protection against malware | Upload re-encoding, SVG rejection, no execution of user files |
| A.8.8 | Management of technical vulnerabilities | Dependency pins, test suite, documented upgrade flow |
| A.8.9 | Configuration management | `APP_ENV` overlays, production secret enforcement |
| A.8.10 | Information deletion | Employee deletion with audit record; retention setting |
| A.8.11 | Data masking | Masked identifiers in recipient-facing evidence views |
| A.8.12 | Data leakage prevention | API responses scoped; PII decryption restricted to admins |
| A.8.13 | Information backup | `scripts/backup_db.sh`, 30-day retention, restore drill |
| A.8.15 | Logging | Structured logs + `audit_logs` + request correlation id |
| A.8.16 | Monitoring activities | `/metrics` (protected), live board, alerting hooks |
| A.8.20 | Networks security | Private DB/Redis network, single public TLS listener |
| A.8.21 | Security of network services | TLS 1.2/1.3, HSTS, CSP, nginx rate limits |
| A.8.23 | Web filtering | Out of scope (endpoint control) |
| A.8.24 | Use of cryptography | AES-256-GCM, bcrypt, TLS, documented key handling |
| A.8.25 | Secure development life cycle | Schema validation, sanitisation, regression tests |
| A.8.26 | Application security requirements | Authn/authz, audit, encryption, input validation |
| A.8.28 | Secure coding | Bound SQL parameters, no dynamic eval, output escaping |
| A.8.32 | Change management | Alembic migrations, documented upgrade/rollback |
| A.8.34 | Protection during audit testing | Test suite runs hermetically; no production data needed |

---

## 3. NIST SP 800-53 Rev. 5 mapping

### 3.1 Access control (AC)

| Control | Implementation |
|---|---|
| AC-2 Account management | Admin invite/list, `is_active`, lockout counters |
| AC-3 Access enforcement | `require_roles`, per-row tenant checks |
| AC-5 Separation of duties | Admin vs manager vs viewer |
| AC-6 Least privilege | Destructive/config routes admin-only |
| AC-7 Unsuccessful logon attempts | 5 failures → 15-minute lock (HTTP 423) |
| AC-11 Session lock / AC-12 termination | Short access lifetime, logout, `token_version`, `jti` revocation |
| AC-17 Remote access | TLS-only public listener |

### 3.2 Audit & accountability (AU)

| Control | Implementation |
|---|---|
| AU-2 Event logging | Create/update/delete of employees, campaigns, settings, users |
| AU-3 Content of audit records | who, action, table, target id, before/after, IP, user agent, timestamp |
| AU-4 Audit storage capacity | Indexed table; retention aligned with `DATA_RETENTION_DAYS` |
| AU-6 Audit review | Query by organization/target; export via SQL/BI |
| AU-9 Protection of audit information | Written in the business transaction; no update/delete API |
| AU-12 Audit generation | `app/services/audit_service.py` |

### 3.3 Configuration management (CM)

| Control | Implementation |
|---|---|
| CM-2 Baseline configuration | `.env.example`, compose file, Alembic head |
| CM-6 Configuration settings | Production secret gate, CORS policy, `TRUST_PROXY_HEADERS` |
| CM-7 Least functionality | Metrics off by default; email/SMS/WhatsApp/voice disabled when unconfigured |

### 3.4 Identification & authentication (IA)

| Control | Implementation |
|---|---|
| IA-2 Identification and authentication | Unique usernames, bcrypt |
| IA-4 Identifier management | UUID primary keys |
| IA-5 Authenticator management | Policy, rotation on change, revocation, no default admin password in production |
| IA-6 Authentication feedback | Generic "Incorrect username or password"; specific lockout notice only |
| IA-8 Non-organizational users | Not applicable (internal operators only) |

### 3.5 System & communications protection (SC)

| Control | Implementation |
|---|---|
| SC-4 Information in shared resources | Tenant scoping, no cross-org cache keys |
| SC-7 Boundary protection | nginx edge, private DB/Redis network |
| SC-8 Transmission confidentiality | TLS 1.2/1.3, HSTS |
| SC-12 Cryptographic key establishment | `SECRET_KEY`/`ENCRYPTION_KEY`, ≥ 32 chars, secret manager |
| SC-13 Cryptographic protection | AES-256-GCM, bcrypt, HMAC-signed JWT |
| SC-23 Session authenticity | Signed JWTs with expiry, `ver`, `jti` |
| SC-28 Protection of information at rest | Encrypted PII columns, encrypted payloads, encrypted backups |

### 3.6 System & information integrity (SI)

| Control | Implementation |
|---|---|
| SI-2 Flaw remediation | Documented upgrade path, dependency pins |
| SI-3 Malicious code protection | Upload re-encoding, active-content rejection |
| SI-4 System monitoring | Metrics, structured logs, live board |
| SI-10 Information input validation | Pydantic schemas, sanitisation, size caps |
| SI-11 Error handling | JSON error contract; internals never leaked |

### 3.7 Incident response (IR) & contingency (CP)

| Control | Implementation |
|---|---|
| IR-4 Incident handling | `SECURITY.md` §3 procedure |
| IR-5 Incident monitoring | Audit/log review, lockout spikes |
| IR-6 Incident reporting | Documented channel and escalation |
| CP-9 System backup | `scripts/backup_db.sh`, restore drill |
| CP-10 Recovery | Documented RPO/RTO, migration rollback |

### 3.8 Awareness & training (AT)

| Control | Implementation |
|---|---|
| AT-2 Literacy training | Campaigns, LMS modules, micro-learning pages |
| AT-3 Role-based training | Department/access-level targeting |
| AT-4 Training records | Interaction ledger, Elo history, monthly archives, certificates |

---

## 4. Data handling policy

### 4.1 Classification

| Class | Examples | Handling |
|---|---|---|
| **Restricted** | Encryption/secret keys, provider API keys, captured passwords | Secret manager only; never in chat, tickets or the repo |
| **Confidential** | Employee PII, audit logs, campaign results, backups | Encrypted at rest, admin-only access, no external sharing |
| **Internal** | Templates, aggregate metrics, training catalogue | Authenticated staff only |
| **Public** | Branding logo endpoint, public training landing pages | No PII |

### 4.2 Lawful basis & notice (GDPR Art. 6/13, ISO A.5.34)

- Use is limited to **authorized security-awareness simulations** on
  company-owned addresses/assets, with a documented lawful basis (legitimate
  interest or employee consent as advised by counsel).
- Employees must be informed in advance that simulations occur, what is
  recorded (clicks, submissions, device/browser metadata, IP) and why.
- No real passwords should ever be entered into simulation pages; the UI states
  this. Captured values are used only as training evidence.
- Special-category data must not be loaded into the platform.

### 4.3 Minimisation

- Store only the fields needed for training and reporting.
- The recipient-facing evidence API masks identifiers; passwords are stored as
  length/strength metadata where the client opts out of secret capture.
- Device fingerprinting is limited to the fields listed in the dossier schema.

### 4.4 Retention & deletion

| Data | Default retention | Mechanism |
|---|---|---|
| Interaction ledger / campaign results | `DATA_RETENTION_DAYS` (365) | Organization setting + purge job |
| Audit logs | 365 days (recommended ≥ 1 year) | SQL retention job |
| Revoked JWTs | 30 days | Automatic prune in `revoke_token` |
| Backups | 30 days | `scripts/backup_db.sh` |
| Employee records | Until offboarding + retention window | Admin delete (audited) |

Deletion requests are executed by an admin; the audit row (without the deleted
PII snapshot where legally required) is retained as proof of deletion.

### 4.5 Cross-border transfer

Deploy in the region required by the organization. Sender providers
(Brevo/TextBee/WA-AKG/IllyVoIP/LLM) may process data outside that region:
record the transfer mechanism (SCCs/DPA) before enabling each channel.

### 4.6 Access review

Quarterly: review `/api/v1/users` (admin), disable leavers, verify that only
admins hold admin role, and sample `audit_logs` for unexpected changes.

### 4.7 Breach notification

Follow `SECURITY.md` §3; notify the DPO/legal owner immediately. GDPR requires
notification within 72 hours of awareness when a personal-data breach is likely
to result in risk to individuals.

---

## 5. Control evidence index

| Evidence | Where |
|---|---|
| Audit trail schema | `backend/app/models/audit.py`, migration `0018` |
| Lockout and policy code | `backend/app/api/v1/auth.py`, `app/schemas/password_policy.py` |
| Encryption service | `backend/app/services/encryption_service.py` |
| Session revocation | `backend/app/deps.py`, `app/services/audit_service.py` |
| Boundary/headers/limits | `nginx/humint-shield.conf`, `frontend/nginx.conf` |
| Backup procedure | `scripts/backup_db.sh`, `DEPLOYMENT.md` §6 |
| Test evidence | `backend/tests/`, coverage gate 80% |
| Incident procedure | `SECURITY.md` §3 |

## 6. Known gaps to close before a formal audit

1. External penetration test and remediation sign-off.
2. SIEM forwarding of `audit_logs` (currently queryable in-database).
3. Automated retention purge job scheduling in the deployment.
4. Documented DPA/SCC records for each enabled third-party sender.
5. Annual access review and security-awareness attestation for operators.
