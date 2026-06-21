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
- P1: Wire real 3CX Call Control API for live outbound calls + call recording.
- P1: Office 365 SSO live OAuth flow; bulk CSV lead import; campaign auto-dialer queue.
- P1: SMS channel (provider abstraction already supports adding it alongside WhatsApp).
- P2: Vector search for KB retrieval; TPS/CTPS registry API check; analytics export.

## Iteration 1.1 (2026-06-21) — 5 feature areas
- One-command local startup: `./start.sh` / `make dev` (env+dep+Mongo validation, health URLs, graceful shutdown); `.env.example` templates; `GET /api/health`.
- WhatsApp (Meta Cloud API): provider abstraction + mock, send w/ retries+dead-letter, signed webhook (X-Hub-Signature-256) + verify handshake, lifecycle states, rate limiting, PII-redacted logs. New `/messaging` page.
- ElevenLabs fix: deterministic `select_tts_provider`/`generate_tts`; test calls now use ElevenLabs (model+stability/style applied) with no silent fallback; key Validate endpoint+button.
- Audit log: append-only `record_audit` (actor, action, entity, before/after diff, source IP, UTC, correlation id via middleware); `GET /api/audit` filters; Settings→Audit viewer.
- KB opening mode: scripted vs KB-guided openings with guardrails + fallback; KB paste + pdf/txt upload; Settings→Opening & KB.
- Tests: `backend/tests/` pytest (53 passing). Docs: README + CHANGELOG.

## Iteration 1.2 (2026-06-21) — BYO models, company overview, script types, Windows
- Windows easy setup: `start.bat` (validates deps/env/Mongo, opens backend+frontend) + README Windows section.
- Bring-your-own LLM keys: per-workspace OpenAI/Anthropic/Gemini keys (falls back to Emergent key); provider + **model dropdowns** (`GET /api/llm/models`); `POST /api/settings/integrations/llm/test` validates a key (distinguishes valid / quota-exceeded / invalid). Saved-keys transparency row with per-provider clear (fixes sticky-key bug).
- Company Overview (renamed from Opening & KB): upload/paste company docs, **activate/disable multiple** (`active` flag + `PUT /api/kb/{id}/toggle`). Active docs feed the live agent so it can answer off-script company questions, and (in KB opening mode) the opening line.
- Script types: **line-by-line** (follows script; answers unaccounted questions from company overview) and **personality-driven** (persona generates a unique conversation). Stored on script; agent behavior branches by type.
