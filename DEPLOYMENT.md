# HUMINT Shield — Deployment & Operations Guide

This document covers the production deployment of HUMINT Shield behind TLS,
the protected metrics endpoint, host hardening (`fail2ban`) and the automated
database backup.

> The application is defence-training software. Deploy it only for employees of
> the organization that commissioned it and only against company-owned
> addresses/assets, in line with your written authorization.

---

## 1. Prerequisites

| Component | Minimum |
|---|---|
| Docker Engine + Compose v2 | 24.x / 2.20 |
| Host | 2 vCPU, 4 GB RAM, 20 GB disk |
| Public DNS | `humint.example.com` → host IP |
| Certificates | Let's Encrypt (certbot) or corporate PKI |
| PostgreSQL | 16 (provided by `docker-compose.yml`) |
| Redis | 7 (provided; enables Celery + distributed rate limits) |

## 2. Environment files

Configuration is layered (`APP_ENV` selects the overlay):

| File | Purpose | Committed |
|---|---|---|
| `backend/.env.example` | Secret-free template | yes |
| `backend/.env.development` | Local defaults | yes |
| `backend/.env.production` | Production placeholders | yes |
| `backend/.env` | **Real secrets** | **never** |
| `.env` (repo root) | Compose interpolation | **never** |

```bash
cp backend/.env.example backend/.env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "import secrets; print('ENCRYPTION_KEY=' + secrets.token_hex(32))"
```

`SECRET_KEY` and `ENCRYPTION_KEY` must be **set explicitly, ≥ 32 characters,
and identical across API/worker/beat processes**. Losing `ENCRYPTION_KEY`
makes every encrypted column unreadable; back it up in your secret manager
(not in the database backup).

Startup refuses to run in production when either key is missing/short or when
`BOOTSTRAP_ADMIN_PASSWORD` is still `ChangeMe123!`.

## 3. Build and start

```bash
docker compose build
docker compose up -d
docker compose exec backend alembic upgrade head
docker compose ps
curl -fsS http://127.0.0.1:8081/healthz
```

`AUTO_CREATE_SCHEMA=false` in production: Alembic owns the schema. The first
admin is seeded from `BOOTSTRAP_ADMIN_*`; sign in and change the password
immediately (profile menu → **تغيير كلمة المرور**).

## 4. TLS termination (nginx edge)

The `frontend` container speaks plain HTTP on the private network. The public
listener is `nginx/humint-shield.conf`:

```bash
# 1. Certificates
sudo certbot certonly --webroot -w /var/www/certbot \
  -d humint.example.com --email security@example.com --agree-tos

# 2. Add the edge service (docker-compose.override.yml)
```yaml
services:
  edge:
    image: nginx:1.27-alpine
    ports: ['80:80', '443:443']
    volumes:
      - ./nginx/humint-shield.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certbot/conf:/etc/letsencrypt:ro
      - ./certbot/www:/var/www/certbot:ro
      - /etc/nginx/.metrics_htpasswd:/etc/nginx/.metrics_htpasswd:ro
    depends_on: [frontend]
```

```bash
docker compose up -d edge
```

See `nginx/README.md` for the standalone (non-compose) option.

What the edge block enforces:

- `http://` → `https://` **301** for every path except the ACME challenge.
- TLS 1.2/1.3 only, modern ciphers, session cache.
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`.
- `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: strict-origin-when-cross-origin`,
  `Permissions-Policy`, and a same-origin `Content-Security-Policy`
  (`frame-ancestors 'none'`, `object-src 'none'`).
- `limit_req`: **5 r/min/IP** on `/api/v1/auth/login`,
  **60 r/min/IP** on the rest of `/api/v1/*` (HTTP 429 with `limit_req_status`).
- `/metrics`: allowed only from RFC1918/loopback ranges **and** HTTP Basic
  Auth; everything else gets 403.

Renewal:

```bash
# /etc/cron.d/certbot-renew
0 3 * * * root certbot renew --quiet --deploy-hook "docker compose -f /opt/humint-shield/docker-compose.yml exec frontend nginx -s reload"
```

### 4.1 Metrics (optional)

```bash
sudo htpasswd -c /etc/nginx/.metrics_htpasswd prometheus
# mount the file into the edge container, then:
#   METRICS_ENABLED=true   (backend, internal listener only)
curl -u prometheus https://humint.example.com/metrics
```

Keep `METRICS_ENABLED=false` on any deployment without an internal scraper.
Note: the frontend nginx always answers 404 for `/metrics`; only the edge
block (with its allow-list and Basic Auth) can reach the backend.

### 4.2 Client IP behind the proxy

Set `TRUST_PROXY_HEADERS=true` **only** when every request arrives through the
edge proxy/Cloudflare. The backend then uses `CF-Connecting-IP`/`X-Real-IP`
and the *rightmost* `X-Forwarded-For` entry; otherwise it uses the socket peer.
A misconfigured value lets a client choose its own rate-limit bucket.

## 5. Host hardening — fail2ban (SSH)

```bash
sudo apt-get install -y fail2ban
sudo tee /etc/fail2ban/jail.d/humint-sshd.local >/dev/null <<'EOF'
[sshd]
enabled  = true
port     = ssh
backend  = systemd
maxretry = 4
findtime = 10m
bantime  = 1h
bantime.increment = true
bantime.factor    = 2
bantime.maxtime   = 1w
ignoreip  = 127.0.0.1/8 ::1
EOF
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
```

Also: disable password SSH login (`PasswordAuthentication no`), allow only
key-based access, and restrict the Docker ports (5432/6379) to the compose
network — only 80/443 should be published.

Optional nginx jail for repeated 401/429 probing:

```ini
[humint-nginx]
enabled  = true
filter   = nginx-http-auth
logpath  = /var/log/nginx/error.log
maxretry = 10
findtime = 5m
bantime  = 1h
```

## 6. Automated database backups

`scripts/backup_db.sh` writes a dated backup and prunes anything older than
30 days.

```bash
chmod +x scripts/backup_db.sh
sudo mkdir -p /opt/humint-shield/backups
sudo tee /etc/cron.d/humint-backup >/dev/null <<'EOF'
# Daily at 02:15 UTC — PostgreSQL custom-format dump, 30-day retention.
15 2 * * * root cd /opt/humint-shield && BACKUP_DIR=/opt/humint-shield/backups RETENTION_DAYS=30 ./scripts/backup_db.sh >> /var/log/humint-backup.log 2>&1
EOF
sudo chmod 600 /etc/cron.d/humint-backup
```

Behaviour:

| Backend | Command | Verification |
|---|---|---|
| PostgreSQL | `pg_dump --format=custom` | `pg_restore --list` |
| SQLite | `sqlite3 .backup` (online-safe) | SQLite magic header |

Restore drill (run quarterly, on a staging host):

```bash
createdb humint_restore
pg_restore --no-owner -d humint_restore backups/humint_shield_<stamp>.dump
```

Store backups **encrypted** (`age`/`gpg`) and off-host. Audit logs and the
encrypted PII columns are inside the dump; treat a backup as sensitive data.

## 7. Upgrade procedure

```bash
git pull
docker compose build
docker compose exec backend alembic upgrade head
docker compose up -d
curl -fsS https://humint.example.com/healthz
```

Roll back code only together with `alembic downgrade -1` if the release added a
migration; keep a fresh backup before every upgrade.

## 8. Post-deployment checklist

- [ ] `/healthz` returns `{"status":"ok"}` over HTTPS.
- [ ] HTTP returns 301 to HTTPS; HSTS/CSP headers present (`curl -I`).
- [ ] Login limited to 5 attempts/minute from one IP (429 afterwards).
- [ ] Five bad passwords lock the account for 15 minutes (HTTP 423).
- [ ] `/metrics` is 403 without credentials.
- [ ] `alembic current` shows `0018_enterprise_security_hardening`.
- [ ] Admin password changed from the bootstrap value.
- [ ] Backup cron ran once and the dump restores on staging.
- [ ] `fail2ban-client status sshd` shows the jail active.
