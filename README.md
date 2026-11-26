# HUMINT Shield

منصة تدريب توعية أمنية قائمة على الموافقة، مع محاكاة هجمات تصيّد متعددة القنوات
وبيانات قياس سلوكي قابلة للتدقيق. صُمّمت للاستخدام الداخلي المصرّح به فقط،
ضد عناوين وأصول تملكها المؤسسة أو لديها تفويض كتابي باستخدامها.

> **تنبيه استخدام:** هذا المشروع ليس أداة هجوم. لا ترسل بريدًا أو SMS أو
> WhatsApp أو مكالمة صوتية إلى أي شخص دون تفويض موثّق. جميع القنوات تبقى
> معطّلة عندما لا تُضبط مفاتيحها، والبريد الافتراضي في التطوير يعمل بوضع
> `EMAIL_DRY_RUN`.

---

## المحتويات

- [نظرة سريعة](#نظرة-سريعة)
- [آخر إصدار](#آخر-إصدار)
- [المعمارية](#المعمارية)
- [التشغيل السريع بـ Docker](#التشغيل-السريع-بـ-docker)
- [التشغيل المحلي للتطوير](#التشغيل-المحلي-للتطوير)
- [الإعدادات](#الإعدادات)
- [قنوات المحاكاة](#قنوات-المحاكاة)
- [الصلاحيات والأدوار](#الصلاحيات-والأدوار)
- [قاعدة البيانات والترحيلات](#قاعدة-البيانات-والترحيلات)
- [الاختبارات](#الاختبارات)
- [النشر على Cloudflare](#النشر-على-cloudflare)
- [الأمان والتشغيل](#الأمان-والتشغيل)
- [بنية المشروع](#بنية-المشروع)
- [استكشاف الأخطاء](#استكشاف-الأخطاء)
- [الترخيص](#الترخيص)

---

## نظرة سريعة

HUMINT Shield يجمع بين:

- **إدارة التوعية (LMS):** مكتبة وحدات تدريبية، إسنادات، مواعيد استحقاق،
  صندوق بلاغات التصيّد، ودرجات مناعة وسلوك.
- **حملات محاكاة حقيقية:** بريد إلكتروني، SMS، WhatsApp، مكالمات صوتية
  (vishing)، رموز QR، ووسائط USB — كل ذلك ضمن حملة واحدة قابلة للتدقيق.
- **تتبّع دقيق:** فتح، نقر، عرض صفحة، إدخال بيانات في نموذج محاكاة، بلاغ عن
  التصيّد، وإكمال التدريب، مع طوابع زمنية وأحداث متعددة لا تُدمج.
- **ملف تحقيق لكل مستهدف:** خط زمني كامل، مراجع التسليم، الحمولات المشفّرة،
  درجة المناعة، والتصنيف السلوكي.
- **لوحة مراقبة حيّة:** تحديث كل ثانيتين، بطاقة لكل مستهدف، وتنبيهات فورية.
- **إدارة صلاحيات دقيقة:** 24 صلاحية في 9 مجموعات، وأدوار `admin` و`manager`
  و`viewer` و`custom`، مع منح فردي فوق الدور.

**لا تُجمع كلمات مرور حقيقية ولا تُوجّه الروابط إلى مواقع خارجية:** النقر
ينتهي دائمًا إلى صفحة تدريب توعوي شفافة.

---

## آخر إصدار

**2026-11-26 — الإصدار 1.0.0**

- ترحيل `0019_user_permissions`: أعمدة `users.permissions` و
  `users.last_login_at`، وصلاحيات فردية دقيقة.
- إدارة المستخدمين والصلاحيات من الواجهة، مع كتالوج صلاحيات موحّد يُعرض من
  الـAPI بدل تكراره في الواجهة.
- صفحة تغيير كلمة المرور، وسياسة كلمات مرور قابلة للضبط، وتدقيق الدخول.
- تحصين أمني مؤسسي: رؤوس أمان، حدّ لمعدل الطلبات، تدقيق، وتنقية مدخلات.
- قناة SMS عبر **TextBee**، وقناة WhatsApp عبر **WA-AKG**، وقناة صوتية عبر
  **IllyVoIP**، مع تعطيل صريح عند غياب الإعدادات.
- دعم البريد عبر **Brevo** أو **SMTP**.
- تتبّع QR/USB، تسجيل أحداث الجهاز، ولوحة أدلة قابلة للتصدير.

راجع [`CHANGELOG.md`](CHANGELOG.md) لسجل التغييرات.

---

## المعمارية

```text
                         ┌─────────────────────────────────────────────┐
  Brevo / SMTP ─────────►│  FastAPI (API + standalone training pages)  │
  TextBee (SMS) ────────►│                                             │
  WA-AKG (WhatsApp) ────►│  /api/v1/*       REST + JWT + permissions   │
  IllyVoIP (voice) ─────►│  /api/v1/track/* unauthenticated tracking    │
                         │  /training/*     micro-learning              │
                         │  /healthz        liveness                   │
                         └───────┬───────────────────────┬─────────────┘
                                 │ SQLAlchemy 2 async    │ Celery
                         ┌───────▼────────┐      ┌───────▼────────┐
                         │ PostgreSQL 16  │      │ Redis 7.2      │
                         │ or SQLite      │      │ worker + beat  │
                         └────────────────┘      └────────────────┘

  React 18 SPA (Vite) ──► nginx (same-origin) ──► FastAPI
  Cloudflare Tunnel / Worker ──► public HTTPS ──► FastAPI
```

### التقنيات

| الطبقة | التقنية |
|---|---|
| الواجهة | React 18، TypeScript، Vite، MUI 5، React Query 5، Redux Toolkit |
| الخلفية | FastAPI، SQLAlchemy 2 async، Pydantic 2، Alembic |
| قاعدة البيانات | PostgreSQL 16 (إنتاج) أو SQLite (تطوير) |
| المهام | Celery + Redis |
| البريد | Brevo API أو SMTP |
| SMS | TextBee Android Gateway |
| WhatsApp | WA-AKG (واتساب مستضاف ذاتيًا) |
| الصوت | IllyVoIP Voice API |
| الأمان | JWT، bcrypt، AES-256-GCM، صلاحيات دقيقة، تدقيق، Rate limiting |
| الاختبارات | pytest، Jest + Testing Library، Playwright |
| النشر | Docker Compose، nginx، Cloudflare Tunnel/Worker |

---

## التشغيل السريع بـ Docker

### المتطلبات

- Docker Engine 24+ وDocker Compose v2.
- 2 vCPU و4 GB RAM على الأقل.
- مفاتيح مزوّدي القنوات اختيارية؛ اتركها فارغة لتعطيل القنوات.

### 1) الإعداد

```bash
cp .env.example .env
```

حرّر `.env` في **جذر المشروع** (هذا هو الملف الذي يقرأه Docker Compose) واضبط
على الأقل:

```dotenv
SECRET_KEY=<سلسلة عشوائية 64 حرفًا على الأقل>
ENCRYPTION_KEY=<سلسلة عشوائية 64 حرفًا على الأقل>
BOOTSTRAP_ADMIN_USERNAME=admin
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=<كلمة مرور قوية>
BASE_URL=http://localhost:8080
FRONTEND_URL=http://localhost:8080
CORS_ORIGINS=http://localhost:8080
EMAIL_DRY_RUN=true
```

توليد المفاتيح:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> لا تفقد `ENCRYPTION_KEY`: بدونه لا يمكن فك الحقول المشفّرة في قاعدة البيانات.
> احتفظ به في مدير أسرار، وليس في Git.

### 2) التشغيل

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
```

- الواجهة: `http://localhost:8080`
- الـAPI: `http://localhost:8000`
- التوثيق التفاعلي: `http://localhost:8000/api/docs`

إذا لم تُشغّل الترحيلات تلقائيًا:

```bash
docker compose exec backend alembic upgrade head
```

### 3) أول دخول

استخدم بيانات `BOOTSTRAP_ADMIN_*`، ثم غيّر كلمة المرور فورًا من
**الإعدادات ← تغيير كلمة المرور**. لا تُطبع كلمات المرور في السجلات.

---

## التشغيل المحلي للتطوير

### المتطلبات

- Python 3.12 (المشروع مبني على `python:3.12-slim`).
- Node.js 20 وnpm.
- Redis اختياري (يلزم فقط للمهام الخلفية وCelery).

### الخلفية

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

حرّر `backend/.env` واضبط `SECRET_KEY` و`ENCRYPTION_KEY` وبيانات المدير، ثم:

```powershell
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### الواجهة

```powershell
cd frontend
npm ci
npm run dev
```

- Vite: `http://localhost:5173`
- API proxy الافتراضي: `http://localhost:8000`
- إذا أردت تقديم الواجهة والـAPI من أصل واحد:

```powershell
cd frontend
npm run build
cd ..\backend
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

ثم افتح `http://127.0.0.1:8000`. يجب أن يكون `SERVE_FRONTEND=true`، وأن
يشير `BASE_URL` و`FRONTEND_URL` إلى نفس الأصل العام.

### Docker مقابل التشغيل المحلي

| السياق | ملف الإعداد | الواجهة |
|---|---|---|
| Docker Compose | `.env` في جذر المشروع | nginx على `8080` |
| تشغيل محلي | `backend/.env` | Vite على `5173` أو `frontend/dist` |
| Cloudflare | متغيرات بيئة العملية | `frontend/dist` من FastAPI |

---

## الإعدادات

كل الإعدادات موثّقة في:

- [`.env.example`](.env.example) — قالب Docker Compose.
- [`backend/.env.example`](backend/.env.example) — قالب التشغيل المحلي.
- [`frontend/.env.example`](frontend/.env.example) — إعدادات Vite.

### أهم المتغيرات

| المتغير | الافتراضي | الوظيفة |
|---|---|---|
| `DATABASE_URL` | SQLite محلي / PostgreSQL في Compose | اتصال قاعدة البيانات |
| `SECRET_KEY` | — | توقيع JWT؛ مطلوب في الإنتاج |
| `ENCRYPTION_KEY` | — | تشفير الحقول الحساسة AES-256-GCM |
| `BASE_URL` | `http://localhost:8000` | الأصل العام في روابط التتبّع |
| `FRONTEND_URL` | `http://localhost:5173` | أصل الواجهة |
| `CORS_ORIGINS` | `http://localhost:5173` | الأصول المسموحة |
| `SERVE_FRONTEND` | `true` | تقديم `frontend/dist` من FastAPI |
| `AUTO_CREATE_SCHEMA` | `true` | إنشاء الجداول عند البدء (تطوير) |
| `AUTO_SEED` | `true` | إنشاء المدير والبيانات الأولية |
| `EMAIL_TRANSPORT` | `brevo` | `brevo` أو `smtp` |
| `EMAIL_DRY_RUN` | `false` | منع الإرسال الفعلي في التطوير |
| `TEXTBEE_API_KEY` | فارغ | تعطيل/تشغيل SMS |
| `WA_AKG_API_URL` | `http://localhost:3000/api` | خادم WA-AKG |
| `ILLYVOIP_API_KEY` | فارغ | تعطيل/تشغيل المكالمات |
| `RATE_LIMIT_ENABLED` | `true` | حدّ الطلبات |
| `METRICS_ENABLED` | `false` | مقاييس Prometheus |

> في الإنتاج اضبط `AUTO_CREATE_SCHEMA=false` و`AUTO_SEED=false` بعد أول
> تهيئة، واجعل Alembic هو المسؤول عن المخطط.

---

## قنوات المحاكاة

### البريد الإلكتروني

- **Brevo:** `EMAIL_TRANSPORT=brevo` مع `BREVO_API_KEY` و`FROM_EMAIL`.
- **SMTP:** `EMAIL_TRANSPORT=smtp` مع `SMTP_HOST` و`SMTP_PORT`
  و`SMTP_USERNAME` و`SMTP_PASSWORD`.
- استخدم `EMAIL_DRY_RUN=true` للتطوير؛ تُسجّل الرسالة ولا تُرسل.

### SMS — TextBee

- أنشئ جهاز Android عبر TextBee، ثم اضبط `TEXTBEE_API_KEY`.
- `TEXTBEE_DEVICE_ID` اختياري؛ يُستخدم الجهاز الافتراضي عند تركه فارغًا.
- القناة تبقى معطّلة إذا كان المفتاح فارغًا أو غير صالح.

### WhatsApp — WA-AKG

- شغّل نسخة WA-AKG وامسح رمز QR لإنشاء جلسة.
- اضبط `WA_AKG_API_URL` و`WA_AKG_API_KEY` و`WA_AKG_SESSION_ID`.
- `WA_AKG_WEBHOOK_SECRET` يحمي Webhook حالات القراءة والردود.

### الصوت — IllyVoIP

- `ILLYVOIP_API_KEY` مطلوب لتمكين القناة.
- `ILLYVOIP_SIP_USER_ID` و`ILLYVOIP_CALLER_ID` اختياريان؛ عند تركهما
  يستخدم المزوّد الهوية الافتراضية.
- `ILLYVOIP_RECORD_CALLS=false` افتراضيًا.
- لا تُجرِ مكالمات إلا لأرقام مصرّح بها، وضمن نطاق اختبار موثّق.

### QR وUSB

- حملات QR تولّد ملصقات عالية الدقة وتتبّع مسح الجهاز.
- قناة USB تدعم محاكاة توصيل وسيط مادي، مع تسجيل الأحداث ولوحة أدلة.
- راجع `docs/` و`backend/app/services/` للتفاصيل.

---

## الصلاحيات والأدوار

الصلاحيات معرّفة في [`backend/app/permissions.py`](backend/app/permissions.py)
وتُعرض آليًا في إعدادات المستخدمين. الصلاحيات الفعلية = صلاحيات الدور + المنح
الفردية، مع تجاهل أي مفتاح غير معروف.

| الدور | الوصف |
|---|---|
| `admin` | كل الصلاحيات |
| `manager` | إدارة الموظفين والقوالب والحملات والتقارير والتدريب |
| `viewer` | قراءة فقط |
| `custom` | لا صلاحيات افتراضية؛ تُمنح فرديًا |

أمثلة على الصلاحيات: `employees.view`، `campaigns.launch`،
`reports.export`، `settings.guardrails`، `users.manage`، `audit.view`.

---

## قاعدة البيانات والترحيلات

- آخر ترحيل: **`0019_user_permissions`**.
- التحقق من الحالة:

```bash
cd backend
alembic current
alembic heads
```

- تطبيق الترحيلات:

```bash
alembic upgrade head
```

- SQLite للتطوير:

```dotenv
DATABASE_URL=sqlite+aiosqlite:///./humint_shield.db
```

- PostgreSQL للإنتاج:

```dotenv
DATABASE_URL=postgresql+asyncpg://humint:<password>@postgres:5432/humint_shield
```

- لا تُرفع قاعدة البيانات أو نسخ `.db` إلى Git؛ تحتوي بيانات شخصية.
- للنسخ الاحتياطي راجع [`scripts/backup_db.sh`](scripts/backup_db.sh).

---

## الاختبارات

### الخلفية

```bash
cd backend
pytest -q
# بدون قياس التغطية (أسرع):
pytest -q --no-cov
```

### الواجهة

```bash
cd frontend
npm run typecheck
npm run build
npm test
npm run test:e2e
```

> اختبارات Playwright تحتاج تثبيت المتصفحات: `npx playwright install`.

---

## النشر على Cloudflare

### خيار العرض السريع: Quick Tunnel

مناسب للعرض المؤقت فقط. شغّل الخلفية محليًا ثم:

```bash
cloudflared tunnel --url http://127.0.0.1:8000
```

ثم أعد تشغيل الخلفية مع عنوان النفق:

```bash
BASE_URL=https://<tunnel-host> \
FRONTEND_URL=https://<tunnel-host> \
SERVE_FRONTEND=true \
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- الرابط مؤقت ويتغير عند إعادة تشغيل النفق.
- لا تضع رابط النفق داخل الكود أو Git.
- للاستخدام الدائم استخدم Named Tunnel ونطاقًا تملكه.

### خيار Worker + Assets

يوجد في [`cloudflare/`](cloudflare/) Worker يقدّم الواجهة المبنية ويوكّل
`/api/*` و`/s/*` و`/healthz` و`/metrics` إلى الخلفية.

1. انشر `cloudflare/assets` (نسخة `frontend/dist`) مع Worker.
2. اضبط متغير/سر `BACKEND_ORIGIN` على أصل FastAPI العام.
3. انشر باستخدام Wrangler:

```bash
cd cloudflare
npx wrangler deploy
```

> FastAPI/Python لا يعمل داخل Cloudflare Workers. Worker هنا واجهة أمامية
> وProxy فقط، ويجب تشغيل الخلفية على خادم أو نفق يمكن الوصول إليه.

---

## الأمان والتشغيل

- لا تُرفع `.env` أو `.db` أو مفاتيح المزوّدين أو `node_modules` أو `.venv`.
- استخدم `SECRET_KEY` و`ENCRYPTION_KEY` عشوائيين وقويين، واحتفظ بنسخة آمنة
  من `ENCRYPTION_KEY`.
- غيّر كلمة مرور المدير الأولية فورًا.
- راجع [`SECURITY.md`](SECURITY.md) و[`COMPLIANCE.md`](COMPLIANCE.md).
- للتحصين والنشر راجع [`DEPLOYMENT.md`](DEPLOYMENT.md).
- إعدادات الإنتاج: TLS، HSTS، Rate limiting، تعطيل `/metrics` العام،
  وتدوير السجلات.
- كل حدث حساس يجب أن يمر عبر صلاحية صريحة وسجل تدقيق.
- أي قناة خارجية (بريد/SMS/WhatsApp/صوت) تتطلب تفويضًا مكتوبًا وأرقامًا
  وعناوين مملوكة للمؤسسة.

---

## بنية المشروع

```text
backend/
  app/
    api/v1/            مسارات REST والتتبّع والـWebhooks
    models/            نماذج SQLAlchemy
    schemas/           مخططات Pydantic
    services/          البريد، SMS، WhatsApp، الصوت، التتبّع، الأدلة
    permissions.py     كتالوج الصلاحيات والأدوار
    config.py          الإعدادات
  alembic/versions/    ترحيلات حتى 0019
  tests/               اختبارات pytest
frontend/
  src/
    pages/             صفحات React
    components/        مكوّنات الواجهة
    api/               عميل Axios
    hooks/             Hooks
  dist/                ناتج البناء (غير مرفوع)
cloudflare/
  worker.js            Proxy + SPA
  assets/              نسخة الواجهة المنشورة مع Worker
docs/                  وثائق ورسومات
scripts/               أدوات تشغيل ونسخ احتياطي
```

---

## استكشاف الأخطاء

| المشكلة | السبب المرجّح | الحل |
|---|---|---|
| `bootstrap_failed` / `decryption_failed` | `ENCRYPTION_KEY` مختلف عن المفتاح المستخدم سابقًا | استخدم المفتاح الأصلي؛ لا تولّد مفتاحًا جديدًا على قاعدة موجودة |
| الواجهة تظهر لكن API يفشل | `BASE_URL`/`FRONTEND_URL` أو CORS غير مطابق | اضبطهما على الأصل العام الفعلي |
| الصفحة تعمل من Vite ولا تعمل من FastAPI | `frontend/dist` غير مبني | `cd frontend && npm run build` |
| فشل تحميل الصلاحيات | ترحيل `0019` غير مطبّق | `alembic upgrade head` |
| SMS لا يُرسل | `TEXTBEE_API_KEY` فارغ أو الجهاز غير متصل | اضبط المفتاح وتحقق من TextBee |
| WhatsApp لا يُرسل | جلسة WA-AKG غير متصلة | امسح QR وأعد ضبط `WA_AKG_SESSION_ID` |
| المكالمة لا تُنفّذ | `ILLYVOIP_API_KEY` غير صالح | تحقق من المفتاح و`ILLYVOIP_API_URL` |
| 429 عند الدخول | حدّ المحاولات | انتظر أو راجع إعدادات Rate limit |
| 502 من Cloudflare | الخلفية غير مشغّلة أو النفق مغلق | شغّل FastAPI وتأكد من `healthz` |

---

## الترخيص

MIT — راجع [`LICENSE`](LICENSE).

## وثائق إضافية

- [`PROJECT_ARCHITECTURE_AND_DEFENSE.html`](PROJECT_ARCHITECTURE_AND_DEFENSE.html) — تقرير المعمارية والدفاع.
- [`SECURITY.md`](SECURITY.md) — نموذج التهديد والضوابط.
- [`COMPLIANCE.md`](COMPLIANCE.md) — أساس الامتثال والتفويض.
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — النشر والتشغيل والإنتاج.
- [`CHANGELOG.md`](CHANGELOG.md) — سجل الإصدارات.
