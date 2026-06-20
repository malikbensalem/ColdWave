# ColdWave — AI Cold Calling SaaS (PRD)

## Original Problem Statement
Multi-tenant SaaS for AI cold calling with male/female AI voices, 3CX integration, customer test calls to validate scripts & sales campaigns, a CRM to track who is being called and who responded positively, UK cold-calling law compliance (opt-out), GDPR compliance, a credentials playbook, and an admin Settings tab for integrations and user management.

## User Choices
- AI voices: ElevenLabs (built in MOCK mode — browser SpeechSynthesis previews until an API key is added in Settings).
- Conversation/script LLM: Claude Sonnet 4.6 via Emergent Universal LLM key.
- 3CX: configurable integration layer + mocked live calls.
- Auth: JWT email/password + Emergent Google login + Office 365 SSO (configurable).

## Architecture
- Frontend: React (CRA+craco), Tailwind, shadcn/ui, Phosphor icons, recharts. Swiss high-contrast design (Klein-blue primary). Auth via httpOnly cookie + Bearer token (localStorage `coldwave_token`).
- Backend: FastAPI, Motor/MongoDB. Modules: server.py, auth.py, routes.py, models.py, integrations.py, database.py. All routes under `/api`.
- Multi-tenant: every document scoped by `org_id`. Registration creates a new org; user becomes its admin.

## Personas
- Agency admin: configures integrations, manages users, runs campaigns.
- Sales agent: works leads, runs test calls, updates CRM.
- Compliance officer: manages DNC, GDPR erasure, calling hours.

## Implemented (2026-06-20)
- Auth: register/login/logout/me, Google session exchange, JWT+cookie+Bearer, brute-force lockout, admin seeding.
- CRM: contacts CRUD, status pipeline (new/contacted/positive/callback/opted_out/dnc), search/filter, slide-out detail with call history, DNC flagging.
- Campaigns + Scripts (AI generate via Claude) + Voice library (6 UK male/female voices, preview).
- Test Calls: AI role-play (Claude) — start/turn/end with sentiment + opt-out analysis; auto-updates linked lead + DNC.
- Compliance Centre: calling-hours enforcer (Europe/London), DNC list, number checker, GDPR right-to-erasure + audit log, consent tracking.
- Settings: Integrations (3CX, ElevenLabs, LLM, Office 365), Organisation (calling hours/days), User management (invite/role/delete), Credentials Playbook.
- Dashboard: KPIs, call volume chart, pipeline, recent activity. Demo data seeded.

## Known limitations / MOCKED
- ElevenLabs voice synthesis = MOCK (browser speech) until API key added.
- 3CX live calling = MOCK (connection test mocked); configurable.
- Office 365 SSO = config fields only (Azure AD), not wired to live token exchange.
- AI features depend on Emergent LLM key budget (currently very low — needs top-up).

## Backlog / Next
- P0: Top up Emergent LLM budget (script generation currently 500s on budget cap).
- P1: Wire real 3CX Call Control API for live outbound calls + call recording.
- P1: Live ElevenLabs streaming audio in test calls; per-org voice cloning.
- P1: Office 365 SSO live OAuth flow; bulk CSV lead import; campaign auto-dialer queue.
- P2: TPS/CTPS registry API check; webhooks; analytics export; per-user permissions beyond admin/agent.
