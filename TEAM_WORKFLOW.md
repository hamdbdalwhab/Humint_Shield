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

---

## 2. Synchronization
- **Always run `git pull origin main`** before starting any new task or creating a new branch to ensure your workspace is up to date with the latest changes.

---

## 3. Scope of Changes
- **Strict Scope Isolation:** Only modify files directly related to your assigned channel or feature.
- **Do not touch or refactor other channels' code** to prevent cross-team merge conflicts and unexpected regressions.

---

## 4. Database Migrations
- If your work adds, alters, or removes a database table or column, **create a new Alembic migration**.
- **Never edit or delete previous/existing migrations.**

---

## 5. Pull Requests (PR)
- Push your dedicated feature branch to GitHub:
  ```bash
  git push origin feature/[feature-name]-[your-name]
  ```
- Open a Pull Request (PR) targeting the `main` branch.
- The **Project Manager** will review, verify tests, and merge the PR.
