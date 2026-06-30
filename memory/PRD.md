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

## Iteration 4 (2026-06-21) — Super admin, email campaigns, voices, settings UX
- **Watermark removed** from `frontend/public/index.html` (badge + PostHog + emergent.sh tags).
- **Super Admin / Owner**: new `owner` role; seeded `owner@coldwave.ai / Owner123!`. Owner-only `/api/admin/businesses`, `/api/admin/users`, `/api/admin/global-settings` (Platform Admin page). `require_owner` checks the real actor (impersonation does not grant owner powers).
- **Impersonation**: `POST /api/auth/impersonate` + `/api/auth/stop-impersonation`; JWT carries `imp` claim. Owner can impersonate anyone; org-admin only within own org (not owners/self). Layout shows an impersonation banner with Stop.
- **Global + org AI prompt**: owner sets a global system prompt that is PREPENDED; orgs extend via Settings → Organisation `ai_system_prompt`. `attach_system_prefix` injects both into AI calls.
- **Email Campaigns** (new top-level page, MOCK send): connect Gmail/Office 365 (mock), audience targeting from CRM contacts, scheduler (now / scheduled / recurring) via `email_scheduler_loop`. Endpoints under `/api/email*` + `/api/email-campaigns`.
- **Voices tab**: sample-text input, fixed Stop (managed `playAudio`/`stopAudio` in lib/voice.js), per-voice characteristics (name/persona) with global default + org override (`PUT /api/voices/{id}/characteristics`); identity injected into live agent.
- **Settings UX**: ElevenLabs + LLM keys auto-validate (debounced) on paste; ElevenLabs auto-enables on valid key; hid stability/similarity/style; model is now a dropdown (`GET /api/elevenlabs/models`). KB documents now have View/Edit (`PUT /api/kb/{id}`); removed Opening Line Mode section.
- Testing: backend 15/15 iteration_4 suite PASS; frontend flows verified. Email = MOCK, WhatsApp = MOCK.

## Iteration 5 (2026-06-22) — Full RBAC, impersonation v2, AI Blueprints, banning
- **RBAC engine** (`permissions.py`): governable systems (dashboard, leads, campaigns, scripts, voices, email_campaigns, test_calls, whatsapp, compliance, integrations, users, roles, audit, platform_admin, blueprints) with CRUD-per-system + capability flags (view_all_businesses, impersonate_users, manage_blueprints, ban_users, grant_privileges). Built-in owner/admin/agent + custom roles. `/auth/me` returns `permissions` + `capabilities`.
- **Custom roles** (`rbac.py`): owner creates platform-wide default roles (apply to every business); admins create roles for their own business and can only grant capabilities they hold. Endpoints `/api/roles` CRUD + `/api/systems`. UI: shared `RolesManager` (Settings → Roles & Access; Platform Admin → Default Roles). Permission dependency factories `require_perm` / `require_cap`.
- **UI gating**: nav items, Settings tabs, and action buttons hide based on effective permissions (agents lose Integrations, Users, Platform Admin).
- **Impersonation v2**: impersonate a specific user OR preview a role (`{role, org_id}`). Owner → anyone; admins/granted roles → own business only. Sessions reflect the target's privileges; `require_owner` blocks all `/api/admin/*` while impersonating. Banner + Stop.
- **AI Blueprints** (replaces single global prompt): named prompts (`/api/admin/blueprints` CRUD), one default auto-assigned to new businesses, assignable per business or cleared (opt-out). `attach_system_prefix` = blueprint + org extension.
- **User banning**: `/api/users/{id}/ban` (requires `ban_users`, reason mandatory) blocks login (403 + reason) and impersonation; `/unban` restores. Cannot ban self/owner.
- **Platform Admin filters**: search businesses; search + role + business filters for users.
- **Login page**: shows demo owner + admin boxes.
- **Windows 1-command run**: `start.bat` auto-creates `backend/.env` + `frontend/.env` on first run (generates JWT secret); DB auto-seeds (owner, admin, default blueprint, demo) on backend startup.
- Testing: backend 21/21 after fixing role-update audit type bug; frontend RBAC + impersonation verified. Email & WhatsApp remain MOCK.

## Iteration 6 (2026-06-30) — Real 3CX Call Control + manual CRM calling
- **3CX Call Control API (v20) integration** (`telephony.py`): OAuth `client_credentials` token (cached per tenant, refreshed before expiry) → `GET /callcontrol/{dn}/devices` → `POST /callcontrol/{dn}/devices/{deviceId}/makecall`. Real (no mock).
- `/api/settings/integrations/tcx/test` now performs a live auth + device check; added `tcx_verify_tls` setting; Settings 3CX section relabeled (Client ID / API Key, FQDN-without-www hint, TLS toggle).
- **Manual calling from CRM**: `POST /api/calls/dial {contact_id|destination}` originates a click-to-call (rings the org extension's device, then the lead), logs a `manual` call, bumps new→contacted, audits. Honors opt-out/DNC. UI: Call button per lead row + in the detail sheet (disabled for opted-out/DNC).
- **Status**: implementation verified end-to-end against the live PBX (token endpoint reachable, device/makecall flow correct). The supplied test credentials returned **401 at /connect/token** — a 3CX-side credential/config issue (need a Call Control API app's Client ID + API Key with Call Control Access enabled; also the FQDN is `citiq.3cx.co.za` not `www.citiq...`). Test creds cleared from DB after testing.

## Iteration 7 (2026-06-30) — 3CX direct-dial fix (Route Point origination)
- **Bug**: CRM Call rang the agent's own extension (1019) and never dialed the client — a normal 3CX user extension is always a participant in its own call.
- **Fix**: `telephony.make_call` now originates at the **DN level (Route Point)** so the client number is dialed directly with no human leg (device fallback retained for normal extensions). `test_connection` now uses `GET /callcontrol` to confirm the DN is controllable and reports `is_route_point`/`dn_type`. Destination keeps the `+CC` format.
- **Config**: the Route Point DN is `45214521` (same as the API Client ID). Saved + enabled on the demo org.
- **Verified by testing agent (100%)**: live `POST /api/calls/dial {destination:+27625058013}` → `ok, status Dialing, call.destination=+27625058013` (not 1019/route point); test-connection reports Route Point; opt-out/empty guards return 400; CRM Call button disabled for opted-out leads.
- Note: `/app/backend/tests/test_tcx_iter7_routepoint.py` includes a LIVE dial test — placing a real call on each run; run only for phone-side checks.

## Backlog / Next (updated)
- P1: Disable email send-now button while pending (avoid double-count); real Gmail/O365 OAuth + actual delivery when desired.
- P1: Resolve known iter-3 sticky-LLM-key-on-provider-switch edge case.
- P1: Wire real 3CX Call Control API; bulk CSV lead import; auto-dialer queue.
- P2: Vector KB retrieval; analytics export; `$lookup` for admin user/org joins at scale.
