# Team Collaboration & Git Workflow

This document outlines the mandatory development standards and guardrails for all team members contributing to the HUMINT Shield codebase.

---

## 1. Branching
- **Always create a `feature/` branch for new work.**
- **Never commit directly to `main`.**
- Follow the branch naming convention:
  ```bash
  feature/[feature-name]-[your-name]
  ```
  *(Example: `feature/sms-twilio-ahmed`)*

Starting a branch:

```bash
git checkout main
git pull origin main
git checkout -b feature/<feature>-<your-name>
```

- One branch = one topic. Do not bundle unrelated channels in the same branch.
- Never `git push --force` to `main`, and never rewrite shared history.
- Never commit `.env`, `*.db`, `*.log`, `node_modules/`, `dist/` or generated
  screenshots. They are already covered by `.gitignore` — keep them there.

---

## 2. Synchronization
- **Always run `git pull origin main`** before starting any new task or creating a new branch to ensure your workspace is up to date with the latest changes.

Recommended, to keep history linear:

```bash
git fetch origin
git pull origin main --rebase
```

- Rebase your feature branch on `main` rather than merging `main` into it.
- If a rebase conflicts, resolve it **in your branch** — do not "fix" it with a force push to `main`.
- Re-run the quality gates after a rebase (`pytest`, `npm run typecheck`, `npm test`).

---

## 3. Scope of Changes
- **Strict Scope Isolation:** Only modify files directly related to your assigned channel or feature.
- **Do not touch or refactor other channels' code** to prevent cross-team merge conflicts and unexpected regressions.

Ownership map (shared core belongs to the Project Manager):

| Channel / area | Primary files |
| -------------- | ------------- |
| `email` | `backend/app/services/brevo_service.py`, email template APIs |
| `sms` | `backend/app/services/vonage_service.py` (SMS path), `webhooks/vonage.py` DLR |
| `whatsapp` | `backend/app/services/vonage_service.py` (Messages path), `whatsapp-status` |
| `qr` | `backend/app/services/quishing_service.py`, `frontend/src/pages/QrLureLandingPage.tsx`, QR campaign APIs |
| `vishing` / `pretexting` | their call-script services and schemas |
| `usb` | USB-drop service and schemas |
| shared core | `app/config.py`, `app/main.py`, `app/models/*`, `app/services/campaign_launcher.py`, `alembic/` |

- No drive-by refactors, reformatting, or dependency bumps inside a feature branch.
- Adding a dependency? Justify it in the PR and pin the exact version.
- Never weaken a security control (auth, rate limit, encryption, webhook token) to make a test pass.

---

## 4. Database Migrations
- If your work adds, alters, or removes a database table or column, **create a new Alembic migration**.
- **Never edit or delete previous/existing migrations.**

```bash
cd backend
alembic revision -m "describe the change"
alembic upgrade head
alembic downgrade -1     # verify the rollback path works
```

- Every migration must implement both `upgrade()` and `downgrade()`.
- Keep migrations dialect-safe: they are verified on SQLite **and** PostgreSQL.
- Current head: `0011_qr_identity_resolution`. Update the revision table in `README.md` when you add one.

---

## 5. Pull Requests (PR)
- Push your dedicated feature branch to GitHub:
  ```bash
  git push origin feature/[feature-name]-[your-name]
  ```
- Open a Pull Request (PR) targeting the `main` branch.
- The **Project Manager** will review, verify tests, and merge the PR.

Every PR must state:

- **What** changed and **why** (link the issue if one exists).
- **How it was verified** — the exact commands and their output (tests, coverage,
  manual steps, screenshots for UI work).
- **Risk / rollback** — migrations, config or environment changes, and how to undo them.
- Confirmation that no secret, `.env` value or real employee data is included.

Do not self-merge, and do not push to `main` to "save time" — a rejected PR is cheaper
than a broken `main`.

---

## Definition of Done

A change is done when:

1. It is on a `feature/` branch, rebased on the latest `main`.
2. Backend tests pass (`cd backend && python -m pytest -q`, coverage ≥ 80%).
3. Frontend gates pass (`cd frontend && npm run typecheck && npm run lint && npm test`).
4. A migration exists for any schema change, and it upgrades and downgrades cleanly.
5. The PR is open, described, and reviewed by the Project Manager.
