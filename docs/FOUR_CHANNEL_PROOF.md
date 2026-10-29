# Four-Channel Live Proof — 2026-10-29

This document records a real end-to-end run against FastAPI + SQLite on `http://127.0.0.1:8000`. The public simulation endpoints were called without authentication; campaign creation, launch, and result reads used an authenticated admin. No secrets, passwords, or tokens are included here.

## Automated verification

| Check | Result |
|---|---|
| Backend suite | **405 passed**; coverage **89.64%** (required 80%) |
| Frontend suite | **9 suites / 30 tests passed** |
| Frontend typecheck | `tsc -b` passed |
| Frontend lint | `eslint` passed with `--max-warnings 0` |
| Frontend production build | Vite build passed; 4,407 modules |
| Alembic head | `0010_advanced_channels` |

```powershell
cd backend
python -m pytest -q

cd ..\frontend
npm run typecheck
npm run lint
npm test
npm run build
```

## 1. QR / Quishing

- Campaign: `cd6e37bb-69ce-4836-a92e-e86d16bae707`
- Tracking UUID: `1057629c-1a61-4f2d-890c-4086b1a102c7`
- `GET /api/v1/track/qr/{uuid}` → **302** to `http://127.0.0.1:8000/simulation/qr/{uuid}`
- Page visit → `qr_scanned`, `elo_delta: 0`
- First `POST /api/v1/track/submit/{uuid}` → **200**, `credential_submitted`, `submission_count: 1`, `elo_delta: -25`
- Second submit → **200**, `submission_count: 2`, `elo_delta: 0`
- Observed employee Elo after first submit: **975**; after repeat: **975**
- A later, separate browser-smoke campaign submitted the same employee through its own tracking row and applied another `-25`, so the employee's current DB score is **950**. The `975` values above are the per-campaign observations.
- The API response and database row contain **no password**:
  - `password_stored: false`
  - `submitted_password_encrypted IS NULL`
  - `password_length: 26`
  - `field_names: ["identifier", "network", "portal"]`

Exact persisted event excerpt:

```text
qr_scanned          {"channel":"qr","channel_visit":true,"first_click":false,"elo_delta":0}
credential_submitted {"channel":"qr","submission_count":1,"field_names":["identifier","network","portal"],
                      "password_length":26,"password_stored":false,"elo_delta":-25}
credential_submitted {"channel":"qr","submission_count":2,"field_names":["identifier"],
                      "password_length":27,"password_stored":false,"elo_delta":0}
```

The generated PDF (`docs/qr-poster-proof.pdf`) has one page and a 1200×1200 QR image. The extracted QR image matched `generate_qr_png("http://127.0.0.1:8000/simulation/qr/9482a0d6-415c-48e6-ae52-270219bf77bf")` **pixel-for-pixel (100%)**, proving the printed code opens the real simulation page.

Visual proof: `docs/screenshots/13-qr-mobile-portal.png` and `docs/screenshots/17-qr-hacked-reveal.png`.

## 2. Vishing

- Campaign: `7594248c-e43b-446f-b2f4-7bb91eddd6f0`
- Tracking UUID: `803a1afb-d4a8-4f83-abed-cadb0d61df10`
- Visit → `link_click`, `elo_delta: 0`
- Choice `credential_disclosed` → **200**, `credential_disclosed`, `elo_delta: -30`
- Employee Elo: **1000 → 970**
- A subsequent `reported_phish` request was blocked because the outcome was already terminal; Elo stayed **970**

Exact persisted events:

```text
link_click          {"channel":"vishing","channel_visit":true,"first_click":true,"elo_delta":0}
credential_disclosed {"channel":"vishing","choice":"credential_disclosed","elo_delta":-30}
```

The browser displayed the exact caller and script, then the required buttons `إعطاء الرمز` and `إغلاق المكالمة والإبلاغ`.

Visual proof: `docs/screenshots/14-vishing-call.png`.

## 3. CEO Pretexting

- Campaign: `a8869998-beea-4248-bd62-79e5936f3c8d`
- Tracking UUID: `2a81f366-5b5f-43bd-8367-7370ef0ec2a2`
- Visit → `link_click`, `elo_delta: 0`
- Choice `reported_phish` → **200**, `reported_phish`, `elo_delta: +20`
- Employee Elo: **1000 → 1020**
- A subsequent `financial_fraud` request was blocked because the outcome was already terminal; Elo stayed **1020**

Exact persisted events:

```text
link_click     {"channel":"pretexting","channel_visit":true,"first_click":true,"elo_delta":0}
reported_phish {"channel":"pretexting","choice":"reported_phish","elo_delta":20}
```

The page auto-played the two required messages and exposed `شراء البطاقات وإرسال الأكواد` and `رفض وإبلاغ الأمن`.

Visual proof: `docs/screenshots/15-ceo-pretexting.png`.

## 4. USB Drop

- Campaign: `57e7f625-a7ca-49e0-b4e0-322ec8481598`
- Tracking UUID: `4ba5d3d35bcc4bd99dc3218b595bc7c6`
- `POST /api/v1/campaigns/{id}/generate-usb-html` → **200 `text/html; charset=utf-8`**, 8,506 bytes
- `Content-Disposition` contains:
  `filename="salary_secrets.html"; filename*=UTF-8''%D8%A7%D9%84%D8%B1%D9%88%D8%A7%D8%AA%D8%A8_%D8%A7%D9%84%D8%B3%D8%B1%D9%8A%D8%A9.html`
- The HTML contains the exact warning:
  «لقد قمت بتوصيل فلاشة مجهولة. تم اختراق جهازك الآن. هذا كان اختباراً تدريبياً.»
- The HTML contains **no `<form>`**, no input, no local-file access, and no `.exe`/`.bat`.
- First `GET /api/v1/track/usb/{uuid}` → **200** and `usb_opened`, `first_open: true`, `elo_delta: -30`
- Employee Elo: **1000 → 970**
- Second open → `usb_opened`, `first_open: false`, `elo_delta: 0`; Elo stayed **970**
- Opening the downloaded HTML through a local static server produced a third `usb_opened` row with `first_open: false`, confirming the artefact itself performs the tracking request.

Exact persisted events:

```text
usb_opened {"channel":"usb","first_open":true,"elo_delta":-30}
usb_opened {"channel":"usb","first_open":false,"elo_delta":0}
usb_opened {"channel":"usb","first_open":false,"elo_delta":0}
```

Visual proof: `docs/screenshots/16-usb-html-warning.png`.

## Files and limitations

- The QR proof PDF is committed at `docs/qr-poster-proof.pdf`.
- The five screenshots are retained locally under `docs/screenshots/`; that directory is intentionally git-ignored because it contains historical UI captures.
- Live proof was run against the local SQLite database `backend/humint_dev.db`. The previous Cloudflare quick tunnel expired; the ignored `backend/.env` now points to `http://127.0.0.1:8000` for local operation.
- Email click/report Elo still depends on real Brevo delivery, which is blocked by the Brevo IP allowlist. The code paths are covered by the backend suite.
