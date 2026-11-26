# Changelog

All notable changes to HUMINT Shield are documented here.

## [1.0.0] — 2026-11-26

### Added

- Granular operator permissions: 24 permission keys, 9 groups, four role
  presets (`admin`, `manager`, `viewer`, `custom`) and per-account grants.
- Alembic migration `0019_user_permissions` (`users.permissions`,
  `users.last_login_at`).
- User and permission administration API and UI.
- Password-change page and configurable password policy.
- Enterprise security hardening: audit events, token versioning, request
  limits, security headers and input sanitisation.
- TextBee SMS transport with explicit channel readiness checks.
- Self-hosted WA-AKG WhatsApp transport and webhook handling.
- IllyVoIP outbound voice/vishing channel with TTS and call status tracking.
- QR tracking enhancements and USB telemetry/evidence tooling.
- Monthly archives, department support and short-link records.
- Deployment, security, compliance, thesis and architecture documentation.
- Cloudflare Worker configuration through the `BACKEND_ORIGIN` environment
  variable; the repository no longer embeds a temporary tunnel URL.

### Changed

- Email delivery supports both Brevo and SMTP.
- Removed the retired Vonage service and SDK dependency.
- Expanded campaign, dossier, live-board and reporting interfaces.
- Updated the frontend build and Cloudflare static assets.
- Refreshed the README with current architecture, setup, configuration and
  troubleshooting instructions.

### Security

- `.env`, databases, local Redis binaries and sensitive screenshots remain
  excluded from Git.
- No outbound email, SMS, WhatsApp message, voice call or TTS is sent unless
  the corresponding provider is configured and an authorised operator
  launches it.
