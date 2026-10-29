# HUMINT Shield — Project Status

- **Last updated:** 2026-10-29
- **Branch:** `main`
- **Runtime:** Windows, Python 3.14.5, Node/Jest, SQLite
- **Local backend:** `http://127.0.0.1:8000`
- **Tunnel:** the previous quick tunnel `https://package-conferencing-bingo-successful.trycloudflare.com` no longer resolves; local verification used `http://127.0.0.1:8000`.
- **Frontend build:** `frontend/dist` (Vite, served by FastAPI)

---

## 1. Completed Modules

### Module 1 — AI Template Generation

- **Endpoint:** `POST /api/v1/ai/generate-template`
- **Request:** `target_department`, `scenario`, optional `channel`
- **Response:** `subject`, `body_html`, `difficulty_level`, `provider`, `model`
- **Provider:** Dahl Inference, OpenAI-compatible API
  - Base URL: `https://inference.dahl.global/v1`
  - Primary model: `deepseek-ai/DeepSeek-V4-Flash-0731`
  - Fallback model: `MiniMaxAI/MiniMax-M2.7` via `LLM_FALLBACK_MODELS`
  - Key is configured in the ignored `backend/.env`; it is not committed.
- **Prompt context:** organization industry from the authenticated user's DB record, target department, scenario, and channel.
- **Safety:** the model returns `body_text`; the backend escapes it and wraps it in a fixed, safe RTL HTML shell. If a model returns `body_html`, it is still sanitized (scripts, event handlers, dangerous URLs removed). Output is validated before returning. Provider failures return explicit **`424`** so Cloudflare passes the JSON error detail; missing configuration returns `503`. There is no mock template.
- **Cloudflare resilience:** the primary model has a 30-second budget, the fallback has 60 seconds, and the frontend Axios timeout is 150 seconds. A `429` or timeout from the primary transparently retries the fallback. This keeps normal generation inside Cloudflare's request window.
- **Authorization / limits:** admin and manager only; 10 requests per minute.
- **UI:** Create Template modal has the exact visible button **“✨ Generate with AI”**, loading state, error alert, and autofill for name, subject, body, channel, and difficulty.
- **Current live state (2026-10-26):** DeepSeek still returns **HTTP 429 `model_concurrency`**. The automatic fallback to MiniMax returned a real **`200` in 16.73 seconds** for `السكرتارية` + `تحديث كلمة المرور` with Arabic `subject`, valid RTL `body_html`, `difficulty_level: 5`, and `model: MiniMaxAI/MiniMax-M2.7`. The same generation was repeated from the browser UI: subject, body, and difficulty were autofilled and the previous Cloudflare error disappeared. Click **Allocate** in Dahl to restore DeepSeek as the preferred model.

### Module 2 — Elo Adaptive Difficulty

- **Field:** `human_assets.elo_score`, integer, default `1000`, backfilled by Alembic `0008_elo_rating`.
- **Deltas:** first click `-32`; first simulated report `+32`; repeated events do not double-apply.
- **Difficulty bands:**
  - `< 900` → Easy, template difficulty `1–3`
  - `900–1100` → Medium, template difficulty `4–7`
  - `> 1100` → Hard, template difficulty `8–10`
- **Threat badges:** Low `>= 1101`; Medium `900–1100`; High `800–899`; Critical `< 800`.
- **Launcher:** selects per recipient from active templates in the correct band and channel; rotates by `employee.total_tests_received`; falls back to the campaign template when the band has no candidate.
- **UI:** employee dossier shows `Elo` and a Low/Medium/High/Critical badge; campaign results show Elo, threat level, and delivered template difficulty.
- **Live selection probe:** employee Elo `1000` → band `medium`, range `(4, 7)`, selected `HR Portal · Employee Records Review` difficulty `4`; campaign fallback was `Urgent Password Change` difficulty `3`.
- **Live delta note:** existing live events predate the Elo migration, so all current employees are still at `1000`; delta behavior is covered by backend tests and will apply on the next real click/report.

### Module 3 — Simulated Attack-Chain Reveal

- Email click still opens `/phish/{uuid}` (the credential form).
- After form submission, the recipient is routed to `/hacked/{uuid}`.
- `/hacked/{uuid}` displays a terminal/Matrix typing sequence:
  - `Bypassing firewall...`
  - `Extracting credentials...`
  - `Accessing HR database...`
  - `Downloading 5GB of files...`
- After 5 seconds it interrupts with the red banner:
  - **“STOP! This was a simulation. In a real attack, your credentials would have caused this damage.”**
- A **“متابعة إلى التدريب”** CTA opens the training experience; there is no silent auto-redirect.
- Training page lists derived compromised assets with Arabic primary and English secondary labels, e.g.:
  - `كلمة مرور بريدك الإلكتروني` / `Your Email Password`
  - `الوصول إلى الأنظمة الداخلية المتاحة من حسابك` / `Access to Internal Systems`
- Assets are derived only after a real `submitted_at`; secrets are never returned. Live submitted context returns 4 assets; an unsubmitted tracking row returns 0.
- The terminal and red English banner are forced LTR inside the RTL app so they render correctly.

### Module 4 — Executive PDF Report

- **Endpoint:** `GET /api/v1/reports/executive-pdf?campaign_id={id}`
- **Authorization:** authenticated organization member (including viewer); campaign must belong to the user's organization, otherwise `404`.
- **PDF contents:**
  - Campaign summary and Arabic RTL text
  - Open/Click pie charts
  - Risky-department bar chart
  - Top 5 highest-risk employees by Elo, with department, threat level, clicks, and submissions
  - Arabic shaping with bundled Amiri fonts
- **Response:** `200 application/pdf`, `Content-Disposition: attachment`, `Cache-Control: no-store`.
- **UI:** Campaign Results page has **“Download Executive Report”**; live download produced a 47,096-byte, 2-page PDF.
- **Live verification:** Arabic text, pie charts, department chart, and top-5 table were extracted from the generated PDF; anonymous access `401`; unknown/foreign campaign `404`.

### Module 5 — Visual Email Builder & Organization Branding

- **Editor:** `frontend/src/components/email-editor/EmailVisualEditor.tsx`; three-panel RTL layout with `dir` attributes (palette left, sandboxed iframe canvas center, properties right).
- **Blocks:** Text, Image, Button, Divider, Spacer, Logo; drag/drop via `dnd-kit`; inline text editing inside the sandboxed iframe; block selection opens type-specific properties.
- **Canvas settings:** email background, content background, global font family (Cairo/Tajawal/Segoe UI/Tahoma/Arial), text/link colours, width, padding, radius, preheader. Verified live; the test-send proof screenshot shows the canvas settings.
- **Button properties:** colour, alignment, font size, link URL; editor overrides are persisted in `design_json`.
- **Merge tags:** dropdown inserts `{{first_name}}`, `{{company_name}}`, `{{tracking_url}}`, `{{department}}`; human labels are shown in the editor, while persisted HTML keeps the tags.
- **Branding:** `GET/PUT /api/v1/organizations/{org_id}/branding`; company name, primary colour, support email, and normalized PNG logo upload/preview/delete. The logo is served publicly at `GET /api/v1/public/branding/{org_id}/logo` so email clients do not need a session.
- **Inheritance:** new templates render the live primary colour on buttons, the company name in the footer, and the branding logo; the editor can override colours per template.
- **Persistence:** `templates.design_json` stores the validated visual document and `body_html` stores the compiled/sanitized output. `design_json` is the source of truth; create/update/test-send recompile and sanitize visual designs, and legacy `body_html` is sanitized before storage.
- **Rendering engine:** `backend/app/services/email_design.py` builds email-client-safe table HTML, injects live branding and `[LOGO]`/`[COMPANY_NAME]`/`[SUPPORT_EMAIL]` placeholders, and calls the allow-list sanitizer. `backend/app/services/template_service.py` re-renders `design_json` at send time, replaces merge tags, rewrites every `<a>` to `/phish/{tracking_uuid}`, appends the 1×1 open pixel, and sanitizes the final HTML.
- **Preview:** Desktop/Tablet/Mobile widths and Dark Mode toggles; the prominent **“إرسال نسخة تجريبية إليّ”** action sends the current design to the signed-in admin/manager email with dummy employee values and tracking disabled.
- **Built-ins:** Alembic `0009_visual_templates_branding` backfilled all 13 built-in templates as `legacy` design documents; their exact HTML remains editable through the visual editor's contenteditable iframe.
- **Live verification:**
  - Visual template saved and reopened: `96e09ed6-f754-4cc5-ad0c-de9c4e945d82`, `mode=blocks`, blocks `[logo,text,button,text,footer]`, `body_html` 4,484 bytes, primary `#0F6CBD`, logo URL, `{{first_name}}`/`{{tracking_url}}`, support footer.
  - AI-generated template saved: `af835efa-cca1-41d0-9fc3-06ea80b308da`, `mode=legacy`, 1,479 bytes, Arabic body, no `<script>`, difficulty 5, real MiniMax fallback (`MiniMaxAI/MiniMax-M2.7`).
  - Test-send reached Brevo and returned the exact IP-allowlist error for `110.238.50.60`; no email was delivered.
  - Branding GET: `Acme Corporation`, `#0F6CBD`, `support@acme.example`; public logo GET `200 image/png 6290`.
- **Proof:** `docs/visual-editor-proof.png`, `docs/backend-rendering-engine-proof.png`, `docs/test-send-proof.png`.

### Module 6 — Quishing (QR) Channel

- **Poster endpoint:** `POST /api/v1/campaigns/{campaign_id}/generate-qr` (admin/manager, organization-scoped). Returns a print-ready A4 PDF with one poster per recipient; repeated downloads reuse the same tracking rows so printed codes never break.
- **QR target:** every poster encodes **`BASE_URL/simulation/qr/{tracking_uuid}`** directly. The legacy `GET /api/v1/track/qr/{uuid}` path remains as a scan-then-redirect alias, but printed codes no longer depend on it.
- **QR generation:** `qrcode` at `ERROR_CORRECT_H`, normalized to **1200×1200 px**, embedded losslessly. The UUID is the only credential in the code.
- **Arabic pretexts:** four built-ins in `quishing_service.py` — `it_security`, `hr_policy`, `finance_bonus`, and `free_coffee` — plus per-campaign `headline`/`body`/`footer` overrides in `campaigns.channel_config.qr`.
- **Tracking:** `qr_scanned` is logged on the mobile visit and is **score-neutral**. The first `credential_submitted` applies **`-25` Elo**; repeats are logged without another deduction. QR submissions force `capture_secret=False`: the backend discards the password and stores only length, identifier, and non-secret fields.
- **UI:** the public mobile page is `/simulation/qr/:trackingUuid`, with a captive-portal WiFi/health-insurance design. The form posts to `/api/v1/track/submit/{uuid}`, then lands on `/hacked/{uuid}?channel=qr` and continues to training.
- **Delivery:** QR campaigns use the `simulation` provider and `available` delivery status; they never call Brevo or Vonage. `launch` materialises the tracking rows.
- **Migration:** `0010_advanced_channels` adds `campaigns.channel_config` (JSONB/JSON) and is applied to the dev database.
- **Tests:** `backend/tests/test_quishing.py` and QR cases in `test_api_tracking.py` cover pretext resolution, 1200 px QR PNG, multi-page PDF, authorization, channel validation, neutral scan, first-submit `-25`, repeat idempotency, and secret non-storage.
- **Live verification (2026-10-29):**
  - Campaign `cd6e37bb-69ce-4836-a92e-e86d16bae707`, tracking UUID `1057629c-1a61-4f2d-890c-4086b1a102c7`.
  - `GET /api/v1/track/qr/{uuid}` → `302` to `http://127.0.0.1:8000/simulation/qr/{uuid}`.
  - First submit → `200`, Elo **`1000 → 975`**, status `submitted`; second submit → `200`, Elo remains **`975`**.
  - DB check: `submitted_password_encrypted IS NULL`, API response contains no password, `password_length=26`.
  - Generated poster QR image matched `generate_qr_png("http://127.0.0.1:8000/simulation/qr/9482a0d6-415c-48e6-ae52-270219bf77bf")` **pixel-for-pixel (100%)**.
- **Proof:** `docs/qr-poster-proof.pdf`.

### Module 7 — Vishing (Voice) Channel

- **Public page:** `/simulation/vishing/:trackingUuid`, an iPhone-style incoming-call interface. After answering, it uses browser speech synthesis for the exact script: «مرحباً، أنا أحمد من الدعم الفني. لقد لاحظنا اختراقاً في حسابك. هل يمكنك إعطائي الرمز الذي وصلك في رسالة نصية؟».
- **Choices:** `إعطاء الرمز` → `credential_disclosed` (**`-30` Elo**); `إغلاق المكالمة والإبلاغ` → `reported_phish` (**`+20` Elo**).
- **Backend:** `POST /api/v1/track/vishing/{uuid}` and `/track/visit/{uuid}?channel=vishing`. Outcomes are terminal and idempotent; any prior outcome blocks a second Elo change. Reporting creates a training report.
- **UI:** the page records the visit, submits the chosen outcome, then redirects to `/training/{uuid}?channel=vishing`.
- **Live verification (2026-10-29):**
  - Campaign `7594248c-e43b-446f-b2f4-7bb91eddd6f0`, UUID `803a1afb-d4a8-4f83-abed-cadb0d61df10`.
  - `credential_disclosed` → `200`, Elo **`1000 → 970`**.
  - Subsequent `reported_phish` → blocked as already recorded, Elo remains **`970`**.
  - Browser screenshot confirms the exact caller, script, and both required buttons: `docs/screenshots/14-vishing-call.png` (screenshots are intentionally git-ignored).

### Module 8 — CEO Pretexting Channel

- **Public pages:** `/simulation/ceo/:trackingUuid` (alias) and `/simulation/pretexting/:trackingUuid`, both rendering a WhatsApp/Teams-style executive chat.
- **Messages:** sequential auto-play of exactly:
  1. «مرحباً، أنا في اجتماع مهم ولا أستطيع التحدث.»
  2. «أحتاج منك شراء 3 بطاقات جوجل بلاي (100$) وإرسال الأكواد هنا فوراً. سأعوضك لاحقاً.»
- **Choices:** `شراء البطاقات وإرسال الأكواد` → `financial_fraud` (**`-30` Elo**); `رفض وإبلاغ الأمن` → `reported_phish` (**`+20` Elo**).
- **Backend:** `/api/v1/track/ceo/{uuid}` (alias) plus the visit endpoint. Outcomes are terminal and idempotent; reporting creates a training report. Redirect uses `?channel=pretexting`.
- **Live verification (2026-10-29):**
  - Campaign `a8869998-beea-4248-bd62-79e5936f3c8d`, UUID `2a81f366-5b5f-43bd-8367-7370ef0ec2a2`.
  - `reported_phish` → `200`, Elo **`1000 → 1020`**.
  - Subsequent `financial_fraud` → blocked as already recorded, Elo remains **`1020`**.
  - Browser screenshot confirms the exact messages and buttons: `docs/screenshots/15-ceo-pretexting.png`.

### Module 9 — Safe USB Drop Channel

- **Primary artefact:** `POST /api/v1/campaigns/{campaign_id}/generate-usb-html` returns the exact file **`الرواتب_السرية.html`** for one recipient, or a ZIP with one folder per recipient when several are targeted. Every HTML file carries that recipient's unique tracking URL.
- **Tracking:** on open, the page issues a single `GET /api/v1/track/usb/{uuid}` (plus an image fallback) and shows the exact required warning: «لقد قمت بتوصيل فلاشة مجهولة. تم اختراق جهازك الآن. هذا كان اختباراً تدريبياً.» The first open logs `usb_opened` and applies **`-30` Elo**; repeats are logged with `elo_delta: 0`.
- **Safety:** the HTML contains no form, input, local-file access, executable, macro, auto-run instruction, credential collection, or external library. It only performs the tracking request and renders the warning; it links to `/training/{uuid}?channel=usb`.
- **Fallback:** the older inert PDF pack (`راتب_الشهر_القادم.pdf`) remains available at `/generate-usb-pdf` for environments that block HTML.
- **Live verification (2026-10-29):**
  - Campaign `57e7f625-a7ca-49e0-b4e0-322ec8481598`, UUID `4ba5d3d35bcc4bd99dc3218b595bc7c6`.
  - HTML download: `200 text/html; charset=utf-8`, `Content-Disposition` carries `filename*=UTF-8''...الرواتب_السرية.html`, 8,506 bytes, exact warning present, no `<form>`.
  - First open → `usb_opened`, Elo **`1000 → 970`**; second open → no extra deduction; opening the downloaded file through a local static server produced a third `usb_opened` evidence row with `first_open: false`.
  - Browser screenshot of the live warning: `docs/screenshots/16-usb-html-warning.png`.
- **Tests:** `backend/tests/test_usb_drop.py` — 19 tests covering filenames, ZIP folder contract, authorization, exact warning, tracking URL, no executable/form, and first-open Elo.

### Module 10 — Operator Experience, SOC Simulation & Defensive Playbook

- **Campaign wizard:** supports Email, SMS, WhatsApp, QR, Vishing, Pretexting, and USB. Vishing/pretexting are no longer API-only.
- **Campaign detail:** QR poster download, USB HTML/PDF downloads, and per-recipient **copy simulation link** controls for vishing and pretexting.
- **SOC dashboard:** the endpoint-investigation screen is explicitly labelled a **local simulation**; it does not claim to inspect a real EDR.
- **Security Recommendations:** a real dashboard tab backed by `DEFENSIVE_PLAYBOOK.md`, with validated Markdown content and API tests.
- **Proof screenshots:** `docs/screenshots/13-qr-mobile-portal.png`, `14-vishing-call.png`, `15-ceo-pretexting.png`, `16-usb-html-warning.png`, `17-qr-hacked-reveal.png` (ignored by git, retained locally).

---

## 2. Verification Evidence

### Backend

```text
405 passed
Coverage: 89.64% (required 80%)
Alembic head: 0010_advanced_channels
```

Run command:

```powershell
cd backend
python -m pytest -q
```

### Frontend

```text
Test Suites: 9 passed, 9 total
Tests:       30 passed, 30 total
Snapshots:   0 total
Time:        103.146 s
Ran all test suites.
```

Run command:

```powershell
cd frontend
npm run test
```

`npm run lint` passes, `npm run typecheck` passes, and `npm run build` succeeds (Vite, 4,407 modules; only the existing main-bundle chunk-size warning). The QR/vishing/pretexting/USB wizard, all public simulation pages, poster/USB downloads, per-recipient copy-link controls, and the `available` delivery status are included in the build.

The frontend suite includes `renderEmail.test.ts`, which verifies that editor-only merge-tag spans are converted back to persisted `{{tags}}` and that editor artifacts are removed. The backend suite includes legacy `body_html` XSS sanitization on create.

### Live endpoint checks

Full four-channel evidence, including exact database event rows, is in `docs/FOUR_CHANNEL_PROOF.md`.

| Check | Result |
|---|---|
| `GET /healthz` local | `200 {"status":"ok","version":"1.0.0"}` |
| Tunnel `/healthz` (2026-10-28, before expiry) | `200 {"status":"ok","version":"1.0.0"}` |
| AI endpoint via tunnel (2026-10-28, before expiry) | `200` in `16.73s` — Arabic subject/body, `difficulty_level:5`, `model: MiniMaxAI/MiniMax-M2.7`; DeepSeek primary returned `429 model_concurrency` and fallback handled it |
| AI endpoint from browser UI | `200` — subject, body, and difficulty autofilled; no Cloudflare error |
| Brevo verify | `200` with `valid:false`, `action_required:ip_allowlist` |
| Draft campaign launch | `502` with exact IP-allowlist message; campaign remains `draft` |
| Executive PDF | `200 application/pdf`, 47,096 bytes, 2 pages |
| Submitted attack context | 4 compromised assets, no secrets |
| Unsubmitted attack context | 0 compromised assets |
| Branding GET | `200` — `Acme Corporation`, `#0F6CBD`, `support@acme.example` |
| Public branding logo | `200 image/png`, 6,290 bytes |
| Visual template save/reopen | create/reopen succeeded; `design_json.mode=blocks`; `body_html` 4,484 bytes |
| AI generation + save | real `200` via MiniMax fallback; saved template `af835efa...` (`legacy`, 1,479 bytes, difficulty 5) |
| Live test-send | `success:false` — exact Brevo IP-allowlist error for `110.238.50.60`; no delivery |
| QR poster pack | `200 application/pdf`, 95,708 bytes, 1 page; embedded QR matched the direct simulation URL pixel-for-pixel |
| QR visit + submit | `302` to `/simulation/qr/{uuid}`; scan score-neutral; first submit Elo `1000 → 975`; second submit stayed `975`; password not stored |
| Vishing failure | `credential_disclosed` → Elo `1000 → 970`; later success choice blocked, Elo stayed `970` |
| Pretexting success | `reported_phish` → Elo `1000 → 1020`; later fraud choice blocked, Elo stayed `1020` |
| USB HTML | `200 text/html; charset=utf-8`, 8,506 bytes, exact `الرواتب_السرية.html` filename, exact warning, no form |
| USB first/second open | first `usb_opened` → Elo `1000 → 970`; second open logged with `elo_delta: 0`; downloaded-file open produced a third evidence row |

---

## 3. Current Environment

- **Database:** SQLite at `backend/humint_dev.db`; Alembic revision `0010_advanced_channels`.
- **Templates:** 17 total (13 built-in + 4 custom); all 17 have non-null `design_json` (16 `legacy`, 1 `blocks`).
- **Branding:** current organization `3ec982ac-edf5-4561-b6f1-b62333f64654` — `Acme Corporation`, primary `#0F6CBD`, support `support@acme.example`; normalized PNG logo stored and served publicly.
- **PostgreSQL:** not available in this environment; SQLite is the active runtime.
- **Python:** 3.14.5. Python 3.11 is not installed.
- **AI:** Dahl key present in ignored `backend/.env`. Primary `deepseek-ai/DeepSeek-V4-Flash-0731` still returns `429 model_concurrency`; automatic fallback `MiniMaxAI/MiniMax-M2.7` is working. Primary timeout 30s, fallback timeout 60s, frontend timeout 150s.
- **Email:** Brevo API key is present, but Brevo rejects the current egress IP. Current blocked IP (live test-send): **`110.238.50.60`**; an earlier campaign launch reported `94.26.222.41`. Egress can rotate.
- **SMS/WhatsApp:** Vonage API key/secret, WhatsApp sender/app credentials, and a test phone are blank. No real SMS/WhatsApp/DLR has been sent.
- **Tunnel:** the previous quick tunnel `https://package-conferencing-bingo-successful.trycloudflare.com` no longer resolves; older quick-tunnel URLs are also dead. Start a new tunnel and update `BASE_URL`, `FRONTEND_URL`, and `CORS_ORIGINS` before external testing.
- **Git:** CLI is available at `C:\Program Files\Git\cmd\git.exe` (not on PATH). `backend/.env`, databases, logs, and `frontend/dist` are ignored.
- **Secrets:** the Dahl key and other credentials exist only in the ignored `.env`; they are not included in this report or the commit.

---

## 4. Next Steps Checklist

- [x] **Dahl:** key is configured; primary DeepSeek still hits `429 model_concurrency`.
- [x] **Cloudflare 502 fix:** provider errors return `424`, primary has a 30s budget, and MiniMax fallback returns `200`; verified via the public tunnel and browser UI.
- [x] **AI fallback:** a real `200` in `16.73s` with Arabic subject/body, `difficulty_level: 5`, model `MiniMaxAI/MiniMax-M2.7`.
- [x] **Visual builder/branding:** editor, design persistence, branding APIs, migration `0009`, and 13 built-in wrappers are complete.
- [x] **Live visual save/reopen:** template `96e09ed6...` saved and reopened; `design_json`/`body_html` verified.
- [x] **Live branding/logo:** `Acme Corporation` / `#0F6CBD` / `support@acme.example`; public logo `200 image/png 6290`.
- [x] **AI-generated template saved:** `af835efa...` — legacy mode, real MiniMax fallback, 1,479 bytes, difficulty 5.
- [x] **Test-send path:** reached Brevo; exact IP-allowlist error returned; preview/test-send UI verified.
- [ ] **Stabilize Dahl primary:** log in at `https://inference.dahl.global/account`, link this key, click **Allocate**, and retry until DeepSeek returns `200` repeatably.
- [ ] **Brevo:** open Brevo → Security → Authorised IPs, add **`110.238.50.60`** and **`94.26.222.41`** (and `46.161.243.54` if that egress is still used), or disable the IP restriction.
- [ ] **Tunnel:** previous quick tunnel expired; start a new one and update `BASE_URL`, `FRONTEND_URL`, and `CORS_ORIGINS` before external testing.
- [x] **Quishing (QR):** direct poster URL to `/simulation/qr/{uuid}`, 1200 px QR, neutral scan, first-submit `-25`, secret-free storage, campaign wizard, and poster download are complete.
- [x] **Vishing + pretexting:** exact scripts/buttons, real tracking endpoints, `-30/+20` Elo, terminal idempotency, public pages, CEO alias, wizard support, and training redirects are complete.
- [x] **USB awareness module (safe):** exact `الرواتب_السرية.html` artefact, single/ZIP delivery, `GET /track/usb/{uuid}` on open, `-30` first-open Elo, repeat evidence rows, and inert PDF fallback are complete.
- [x] **Four-channel live proof:** QR scan/submit, vishing failure, pretexting report, and USB HTML open were exercised against FastAPI + SQLite; database events and Elo deltas match the contract.
- [ ] **Commit advanced channels:** migration `0010`, backend routes/services, public pages, wizard/downloads, tests, and docs are still uncommitted.
- [ ] **Real email:** launch draft campaign `16ccfeb3-f986-46e9-956f-44b3f16e0883` after Brevo allowlists the IP.
- [ ] **Proof of life:** confirm delivery, click `/phish/{uuid}`, submit the form, observe `/hacked/{uuid}` for 5 seconds, then continue to training.
- [ ] **Database proof:** verify `submitted_at` is recorded and the employee's `elo_score` drops by 32 on first click.
- [ ] **PDF proof:** download the Executive PDF from Campaign Results.
- [ ] **Vonage:** configure API key/secret, SMS sender, WhatsApp sender/app credentials, webhooks, and a test phone; then test real SMS/WhatsApp/DLR.
- [ ] **Stable domain:** replace the ephemeral quick tunnel with a permanent domain before production.
- [ ] **Font license:** add the Amiri OFL license file if the bundled fonts will be distributed.
- [x] **Commit:** previous production-readiness work committed as `76c2d86`.
- [x] **Commit this fix:** `b6ab0ba` — AI fallback / Cloudflare fix.
- [x] **Commit visual builder/branding:** local feature commit created; not pushed.
- [ ] **Push:** `main` is ahead of `origin/main`; push when confirmed.

---

## 5. Known Limitations / Blockers

1. **Dahl primary model is capacity-limited; fallback is active.**
   DeepSeek returns `429 model_concurrency`; the provider admits signed-in/paid accounts first. The service now automatically falls back to MiniMax and returns a real template. Click **Allocate** for this key at `https://inference.dahl.global/account` to restore DeepSeek as the preferred model. No mock template is used; both primary and fallback are real providers. MiniMax may take 15–50 seconds and emits a reasoning block, which the parser strips before validating the JSON.

2. **Brevo IP allowlist is blocking email.**
   A live test-send on 2026-10-26 reached Brevo and returned the exact message:

   ```json
   {"message":"We have detected you are using an unrecognised IP address 110.238.50.60. If you performed this action make sure to add the new IP address in this link: https://app.brevo.com/security/authorised_ips","code":"unauthorized"}
   ```

   The UI prefixes this with the recipient address and `brevo rejected the message:`. An earlier campaign launch reported `94.26.222.41`; egress can rotate, so allowlist both addresses or disable the restriction. The draft campaign remains `draft`; no email was sent.

3. **No real email/SMS/WhatsApp proof of life yet.**
   This depends on the Brevo allowlist and Vonage credentials above. The application paths are implemented and tested, but no real provider delivery has occurred.

4. **The previous quick tunnel expired.**
   `https://package-conferencing-bingo-successful.trycloudflare.com` no longer resolves. Start a new tunnel and update `BASE_URL`/`FRONTEND_URL`/`CORS_ORIGINS`; a stable domain is required for production.

5. **Email click/report Elo has no real post-migration event yet.**
   QR, vishing, pretexting, and USB were exercised end-to-end against the live API with real `tracking_events`, `training_interactions`, and Elo deltas. Email click/report still depends on a real Brevo delivery; backend tests cover those paths.

6. **Adaptive template selection is per recipient at launch time.**
   The draft campaign's stored fallback template has difficulty `3`, but the launcher selected difficulty `4` for an Elo-1000 employee in the live probe. This is expected: the fallback is used only when the band has no candidate.

7. **Amiri font license file is not yet bundled.**
   The Amiri font files are present under `backend/app/assets/fonts`; add the OFL license file before redistribution.

8. **Git CLI is not on PATH.**
   Git is available at `C:\Program Files\Git\cmd\git.exe`; the commit was created with that full path. Add Git to PATH for convenience.

9. **Branding/logo and simulation links follow `BASE_URL`.**
   The previous quick tunnel has expired, so generated links must not be distributed until a new tunnel or stable domain is configured. At send time the personalizer re-renders from `design_json` with the current `BASE_URL`, so branding remains dynamic.

10. **Vishing TTS voice availability depends on the recipient browser.**
    The exact Arabic script is fixed in the page, but browser speech synthesis uses the voices installed on the device. If no Arabic voice is available, the text remains visible and the scenario still works; operators should check a representative device before a large exercise.

11. **USB/C2 is intentionally limited to awareness simulation.**
    No real reverse-shell, C2 agent, AV-evasion loader, or Defender-disabling instructions are part of this project. A real payload deployed to employee devices would be malware and is outside the authorized-awareness scope.

---

## 6. Operational Notes

- Restart the backend after changing `.env`; settings are loaded at startup.
- The main AI endpoint intentionally returns `503` when no key is configured and **`424`** when the provider fails; it never silently substitutes a mock template. The `424` is deliberate: Cloudflare replaces origin `5xx` responses with its own HTML error page, which hid the actionable provider message.
- AI generation is rate-limited to 10 requests/minute; PDF generation is rate-limited to 20 requests/minute.
- Primary AI timeout is 30s; fallback timeout is 60s; the frontend Axios timeout is 150s. Keep the combined primary + fallback budget below Cloudflare's request window.
- `backend/.env`, `*.db`, `*.log`, and `frontend/dist/` are ignored and must not be committed.
- The active backend serves the built frontend from `frontend/dist` at `http://127.0.0.1:8000`; external tunnel access is currently unavailable until a new tunnel is started.
- `design_json` is authoritative for visual templates: create/update recompiles and sanitizes `body_html`; the personalizer re-renders from `design_json` with live branding at send time.
- Test sends render the current, possibly unsaved, design with dummy employee values, send only to the signed-in admin/manager email, and disable tracking/link rewriting.
- Branding logos are normalized to PNG in the database and served publicly at `/api/v1/public/branding/{org_id}/logo`; the public endpoint was verified `200 image/png` through the tunnel.
- The visual editor uses `dir="ltr"` on the three-column layout grid and `dir="rtl"` on each panel; MUI's RTL CSS plugin flips `sx.direction`, so intentional layout direction must use `dir` attributes.
- All 17 templates currently have non-null `design_json`; the 13 built-ins are `legacy` wrappers that preserve their exact HTML.
- Runtime PIDs are process-local; verify the active backend/cloudflared processes after any restart.
- QR campaigns are print-only: `launch` marks them `available` and the operator downloads `generate-qr`; no Brevo/Vonage call is made.
- The QR wizard uses an active email template as the scenario reference; the QR poster copy comes from `channel_config.qr`, not the email body.
- QR scan is score-neutral; only the first credential submission applies `-25`, and the password is never persisted.
- Vishing/pretexting outcomes are terminal: once an outcome is recorded, later choices are acknowledged without changing Elo.
- USB HTML applies `-30` on the first `usb_opened`; later opens remain evidence events with `elo_delta: 0`.
- Public simulation routes (`/simulation/qr`, `/simulation/vishing`, `/simulation/ceo`, `/simulation/pretexting`) are intentionally unauthenticated; the tracking UUID is the only credential in the link.
