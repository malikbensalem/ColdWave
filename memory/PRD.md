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

## Iteration 8 (2026-06-30) — bug fixes: test-connection on current input, local install, token cache
- **Test connection uses current form input** (no save required): `POST /settings/integrations/tcx/test` now accepts `{tcx_url,tcx_extension,tcx_username,tcx_password,tcx_verify_tls}` and merges over saved (verified by testing agent).
- **Local run fix**: `start.sh` / `start.bat` now install with `--extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/` so `emergentintegrations` resolves off-Emergent.
- **Token cache correctness**: `telephony._get_token` cache key now includes a hash of the client secret, so a rotated/wrong API key re-authenticates instead of reusing a stale token.

## Big roadmap requested (2026-06-30) — to be phased
- CRM: multi-call history per client; columns Name/Phone/Email/Company/Call status/rating/summary/transcript/campaign/date; summary & transcript popups.
- Campaigns 2.0: run by client filters; schedule; contacted & upcoming lists; live queue (called/next/results); campaign avg rating + usage count.
- Multi-channel (Email/WhatsApp/SMS) schedulers at parity with calls (ratings, usage, contacted lists); AI auto-reply with human approval; per-channel AI blueprints (call/email/whatsapp).
- Live call controls: listen-in, manual trigger, whisper/barge, take over.
- Show 3CX callable countries.
- Editable user roles + change role (RBAC exists; extend UI). Hide GLOBAL prompt from admins (owners only, Platform Admin only, not Settings).
- Ban from Users screen (admin + reason); owner ban any user/company from Platform Admin.
- Voice speed control + voice tweaks in Voices tab (document drawbacks).
- Editable scripts (toggle line-by-line/personality + content); smarter line-by-line that ignores titles/speaker labels.
- White-labelling (fonts, logo, colours, company name) keeping ColdWave branding; admin-configurable by permission.
- Owner: choose per-company feature access; Packages (prebuilt access tiers + price, per-company custom price, limits on calls/customers/features, time-limited access).
- Credit/usage limits: stop campaign when AI/ElevenLabs/3CX credits exhausted + notify company users.

## Iteration 9 (2026-07-02) — CRM 2.0 (multi-call history, ratings, transcripts)
- **Backend**: `GET /contacts` now attaches per-lead `call_count`, `last_call_rating`, `last_call_summary`, `last_call_campaign`, `last_call_date`; `GET /contacts/{id}` returns full enriched call history (`campaign_name`, `rating`, `summary`, `next_action`) via `_enrich_call` + `_campaign_name_map`.
- **Frontend (`Leads.jsx`)**: CRM table gained Email, Rating, Last-summary, Campaign, Last-call columns + per-lead call-count badge. Detail sheet shows full multi-call timeline (rating/sentiment/campaign/status/summary per call). New Summary and Transcript popups (Dialog) render the AI analysis + next action and the full agent/prospect transcript.
- Verified via screenshot smoke test (admin@coldwave.ai): table columns, detail sheet, Summary popup (score 10 + next action), Transcript popup all render correctly.
- SMS channel decision: user wants SMS delivered via **3CX** (not Twilio) when omnichannel schedulers are built.

## Iteration 10 (2026-07-02) — Campaigns 2.0 + P2 batch (voice speed, editable scripts, white-label)
- **Campaigns 2.0**: campaigns now carry an `audience` CRM filter (all/new/contacted/callback/positive/consented) + schedule_type. New endpoints: `GET /campaigns/{id}/analytics` (times_used, avg_rating, positive_rate, sentiment), `GET /campaigns/{id}/queue` (contacted[], upcoming[], next), `POST /campaigns/{id}/dial-next` (live 3CX dial of next queued contact, logged against the campaign). Frontend: campaign cards show audience badge + metric grid; a Queue sheet shows Contacted/Upcoming counts, Next-in-queue with Dial-next, and Called/Upcoming tabs. Tested 100% (iteration_9).
- **Voice speed control**: per-voice speaking speed (0.7–1.2×) stored in org voice_characteristics, applied to ElevenLabs VoiceSettings (safe fallback for older SDK). Slider in Voices → edit dialog.
- **Editable scripts + in-editor mode toggle**: script cards have an edit pencil → dialog to edit name/content/persona and toggle line_by_line ↔ personality (PUT /scripts/{id}).
- **Smarter line-by-line**: agent_reply line-by-line prompt now instructs the AI to never read bracket stage labels / speaker labels / placeholder names; scripted-opening extraction strips leading `[LABEL]`.
- **White-labelling**: org brand_name/logo_url/primary_color; `GET /settings/branding`; Settings → White-label tab (colour picker + live preview + Reset). Layout applies branding app-wide (CSS var primary colour, brand name, logo, retained "Powered by ColdWave" footer). Live-update via `coldwave:branding` CustomEvent (fixed reload bug). Tested (iteration_10).
- Cleanup: demo org branding reset to defaults; george voice speed reset to 1.0.

## Backlog / Next (updated 2026-07-02) — remaining P1/P2
- **P1 — Omnichannel schedulers**: Email/WhatsApp/SMS (SMS via **3CX**, per user) at parity with call campaigns (analytics, usage, contacted lists); AI auto-reply with mandatory human approval queue; per-channel AI blueprints (call/email/whatsapp/sms).
- **P1 — Live call controls**: listen-in, whisper/barge, human take-over on live 3CX calls (requires live 3CX participant/streaming APIs — needs a live PBX to verify).
- **P2 — Packages/tiers & credits**: owner-created tiers (feature access + limits on calls/customers), per-company pricing, credit tracking that auto-stops campaigns + notifies users when AI/ElevenLabs/3CX credits run out.
- **Refactor**: split the ~900-line `routes.py` into contacts/calls/campaigns/settings routers.

## Iteration 11 (2026-07-02) — P2 + P3: AI auto-reply approval queue + per-channel blueprints
- **Per-channel AI blueprints (P3)**: blueprints now carry a `channel` (global/call/email/whatsapp/sms). `messaging._channel_system_prompt(org, channel)` resolves a channel-specific blueprint (else global default) + the org's AI extension + channel-style instructions. Uses the workspace's own LLM config (Settings → AI provider/model), falling back to the Emergent Universal key.
- **AI auto-reply + human approval (P2)**: inbound messages generate an AI **draft** stored in `message_approvals` (state=pending). NOTHING sends without human approval. Endpoints: `POST /messages/approvals/simulate-inbound` (test drafter), `GET /messages/approvals`, `PUT /messages/approvals/{id}` (edit draft), `POST .../approve` (sends via provider — WhatsApp live/mock; sms/email recorded as sent pending live gateway/OAuth), `POST .../reject`. Frontend: Messaging → "AI Approvals" tab with simulate form, editable draft cards, Approve/Save/Reject. Tested end-to-end (AI draft generated, edited, approved→sent mock).
- **KEY FINDING**: 3CX Call Control API has NO SMS or WhatsApp send endpoint. WhatsApp goes via the Meta Cloud API (already integrated — this IS what "3CX WhatsApp" uses). 3CX exposes no public SMS send API; live SMS needs the customer's SMS gateway. Email live send needs Gmail/O365 OAuth setup.

## Remaining phases & prerequisites (2026-07-02)
- **P1 — Omnichannel campaign parity** (email/whatsapp/sms campaigns like calls): buildable; live send blocked per channel (WhatsApp=Meta creds, SMS=gateway, Email=OAuth).
- **P4 — Live call controls** (listen/whisper/barge/take-over): build against 3CX Call Control `POST /callcontrol/{dn}/participants` etc.; NEEDS LIVE-PBX VERIFICATION.
- **P5 — Packages/tiers**; **P6 — Credit tracking/auto-stop+notify**: fully buildable, no external deps.
- **P7 — Auto-dialer loop** (pacing within UK hours, auto-stop on opt-outs): buildable.
- **P8 — Refactor routes.py + a11y polish**.
- **P9 — Test vs Live toggle**: messaging side done (simulate + approve→send). Call side (real test call vs live-with-listen) folds into P4.

## Iteration 12 (2026-07-02) — big batch: local-run fix, per-channel blueprints, owner moderation, opening, voice, specific clients
- **#1 Local run fix**: `emergentintegrations` made OPTIONAL (try/except import) with a **litellm** fallback that uses the workspace's own provider key (Settings → AI) when the Emergent package/key is unavailable. Removed `emergentintegrations` + the litellm wheel-URL from `requirements.txt` (now `litellm==1.80.0`); start.sh/start.bat install emergentintegrations as a **separate non-fatal** step. `pip install -r requirements.txt` now works locally.
- **#2 Per-channel AI blueprints**: blueprints have a `channel` (global/call/whatsapp/sms/email) selectable in Platform Admin; each business gets **3 assignable blueprints** (call/whatsapp/sms) via `PUT /admin/businesses/{oid}/channel-blueprint`. Resolution wired into `attach_system_prefix(org, channel)` (calls) and `_channel_system_prompt` (messaging).
- **#3 Owner cross-org moderation**: `POST /admin/users/{id}/ban|unban`, `PUT /admin/users/{id}/role`, `POST /admin/businesses/{oid}/ban|unban` (business ban cascades to block its non-owner users, reusing the existing banned-user login gate). UI: role dropdown + Ban toggle per user; Suspend/Reinstate per business. (Admins already ban/role within own org — org-scoped.)
- **#4 Admin roles**: already available via RolesManager (business scope in Settings, platform defaults in Platform Admin → Default Roles).
- **#5 Campaign specific clients**: campaigns accept `contact_ids` (audience='specific'); queue targets exactly those clients. UI: searchable contact checklist in New Campaign.
- **#6 Test-call opening**: now derives from the script/blueprint — line-by-line uses the script's first line; **personality/no-script generates a persona+blueprint opening via LLM** (no more hardcoded 'Hello, this is your AI assistant…'). TestCalls: after End, a 'New Test Call' button appears and input disables so you can start fresh.
- **#9 Voice controls**: per-voice **stability + style + speed** sliders and a **Dynamic delivery** toggle (AI varies all three by utterance context via `_dynamic_voice_params`). No pitch (ElevenLabs doesn't expose it). Applied in `generate_tts`.
- Tested: iteration_11.json — backend 19/19, frontend all flows PASS, demo data restored.

## Still TODO (from the user's 10-item list)
- **#7 Email provider connection → Settings**: move Email (Gmail + O365 OAuth) connect UI into Settings; user sets it up there. (Real send needs OAuth app.)
- **#8 SMS section + SMS campaigns**: WhatsApp-like SMS page + 'New SMS campaign' button. (Live SMS best powered by Twilio — see #10.)
- **#10 Twilio calling**: choose 3CX vs Twilio in Settings; test call/SMS/WhatsApp with real numbers + listen-in/manual-override. Creds go in Settings (user provided test SID/token/number). Needs integration_expert playbook + live verification.

## Iteration 13 (2026-07-02) — Twilio config in Settings + telephony provider switch (#10 config part)
- Settings → Integrations now has a **Telephony provider** switch (3cx | twilio) and a **Twilio** section: Account SID, Auth Token, Twilio phone number, "Enable Twilio live calling / SMS" toggle, **Test connection**, Save.
- Backend: `IntegrationSettings` gained `telephony_provider`, `twilio_enabled`, `twilio_account_sid`, `twilio_auth_token`, `twilio_phone_number`. New `POST /settings/integrations/twilio/test` validates creds via httpx Basic-auth against `api.twilio.com/2010-04-01/Accounts/{sid}.json` (no SDK). Tested: real creds → valid ("My first Twilio account" active); bad token → invalid; save round-trips. Demo org reverted to 3cx, token not persisted.
- NOT YET DONE: live Twilio call/SMS placement + the 3CX↔Twilio routing in the dial path, and listen-in/manual-override. (Only config + validation this iteration, per request.)

## Still TODO
- **#7** Email provider connection (Gmail + O365 OAuth) UI under Settings.
- **#8** SMS section (WhatsApp-like) + New SMS campaign button (live SMS via Twilio).
- **#10 (remainder)** Wire the dial path to honour `telephony_provider` (place real Twilio calls/SMS when selected + enabled); listen-in / manual-override.

## Iteration 14 (2026-07-02) — Provider-aware dialing + CRM campaign picker (bug fixes)
- **Dialer no longer hardcoded to 3CX**: new `place_outbound_call(integ, dest, say_text)` dispatches on `integrations.telephony_provider` — places calls via **Twilio** (`telephony.twilio_make_call`, Twilio REST + inline TwiML speaking the opening) when Twilio is selected+enabled, else 3CX. Applied to `/calls/dial` and `/campaigns/{id}/dial-next`. Errors now name the selected provider.
- **CRM campaign picker**: clicking Call on a lead (row or detail sheet) opens a dialog to choose a campaign (or ad-hoc) before dialing; `DialRequest.campaign_id` logs the call against it and seeds the Twilio opening from the campaign's script.
- **FIXED data-loss bug**: `PUT /settings/integrations` used to REPLACE the whole integrations object (defaults wiped unsent fields). Now merges via `model_dump(exclude_unset=True)` + `$set integrations.<k>` — partial saves no longer wipe secrets.
- Verified: iteration_12.json — backend 5/5, frontend both entry points, integrations merge regression-tested. Buttons made provider-agnostic ("Call").
- ⚠️ During earlier curl testing the demo org's **3CX API Client ID/Key and ElevenLabs key were cleared** (before the merge fix landed). URL/extension restored; the secret keys must be re-entered in Settings → Integrations.

## Still TODO
- **#10 (remainder)**: AI conversation over Twilio (Media Streams websocket) for full two-way AI calls; listen-in / whisper / barge / take-over.
- **#7** Email provider connection (Gmail + O365 OAuth) UI under Settings.
- **#8** SMS section (WhatsApp-like) + New SMS campaign button (live SMS via Twilio).

## Iteration 15 (2026-07-02) — Live Twilio calls run the AI agent (script + blueprint + ElevenLabs voice)
- **New `twilio_voice.py`** — Twilio Programmable Voice webhooks that run a **turn-based AI cold call** using the campaign's script/blueprint + ElevenLabs voice, the SAME generation pipeline as Test Calls:
  - `POST /api/telephony/twilio/voice/{call_id}` → `<Play>` (ElevenLabs) or `<Say>` fallback the script-driven opening + `<Gather input="speech">`.
  - `POST /api/telephony/twilio/turn/{call_id}` → `agent_reply()` on the prospect's speech → next turn; detects opt-out/close → `<Hangup/>`; handles silence.
  - `GET /api/telephony/twilio/audio/{token}.mp3` serves ElevenLabs audio to Twilio; `POST .../status/{call_id}` analyses the transcript on completion (summary/sentiment/rating → CRM).
- `routes.build_campaign_call_context()` builds script_content/script_type/personality/company_overview/voice + opening (voice identity injected) and is stored on the call; `dial_contact` & `campaign_dial_next` pre-insert the call and drive Twilio via the voice webhook URL. Replaces the old static "this is an automated call… please hold" Polly greeting.
- Verified: iteration_13.json — backend 6/6 PASS (regression tests at `/app/backend/tests/test_twilio_voice_webhook.py`). Uses `<Say>` fallback only because the demo EL key was cleared; `<Play>` (campaign ElevenLabs voice) activates once an ElevenLabs key is set + the campaign has a voice.
- KNOWN (prod note): `_AUDIO` is an in-process cache — fine for a single worker; move to object storage if horizontally scaled.
- ⚠️ Re-enter in Settings → Integrations: **ElevenLabs API key** (for the campaign voice on calls) and the **3CX API key** (both cleared during earlier testing).

## Backlog / Next (updated)
- P1: Disable email send-now button while pending (avoid double-count); real Gmail/O365 OAuth + actual delivery when desired.
- P1: Resolve known iter-3 sticky-LLM-key-on-provider-switch edge case.
- P1: Wire real 3CX Call Control API; bulk CSV lead import; auto-dialer queue.
- P2: Vector KB retrieval; analytics export; `$lookup` for admin user/org joins at scale.

## Iteration 16 (2026-07-13) — Real-time streaming voice (ConversationRelay) + Live Calls monitoring + human takeover
- **Streaming engine pivot (P0 Task 1)**: new `conversation_relay.py` implements Twilio **ConversationRelay** over a WebSocket for low-latency, **interruptible** AI calls. `POST /api/telephony/twilio/relay/voice/{call_id}` returns `<Connect><ConversationRelay url="wss://…/api/telephony/twilio/relay/ws/{call_id}" welcomeGreeting=opening interruptible="any" reportInputDuringAgentSpeech="speech" dtmfDetection="true" voice=<gender-mapped en-GB> language="en-GB"/>`. Uses **Twilio built-in transcription** (per user choice) and the **settings-driven LLM** (agent_reply). WS handles setup/prompt/interrupt/error; cancels the in-flight LLM turn on `interrupt` (barge-in); persists transcript live; analyses transcript on disconnect. Smoke-tested locally end-to-end (setup+prompt → LLM reply streamed back → transcript persisted).
- **Voice-mode switch**: `IntegrationSettings.twilio_voice_mode` = `stream` (ConversationRelay, default) | `gather` (classic turn-based `twilio_voice.py`). `_twilio_webhooks(call_id, integ)` picks the webhook accordingly. Settings → Integrations → Twilio has a segmented **AI voice mode** control (testids `voice-mode-stream` / `voice-mode-gather`).
- **Live Calls monitoring + human takeover (P0 Task 2)**: new page `/live-calls` (nav `Live Calls`) polls `GET /api/calls/live/active`, shows active calls + a live transcript panel (2s poll). **Take over** (`POST /api/calls/{id}/takeover {human_number}`) redirects the in-progress Twilio call to `<Dial>` the human (sets `handoff`, stops the AI). **End** (`POST /api/calls/{id}/hangup`) completes the call. Both guard to active Twilio calls only. `telephony.twilio_update_call` / `twilio_hangup_call` added (Twilio REST, no SDK).
- Verified: iteration_14.json — backend **9/9 pytest pass**; frontend login, nav, Live Calls page render, voice-mode persistence + integrations partial-merge regression all pass. NOTE: true live audio needs a deployed public WSS host + Twilio enabled — verify on deploy (per user).
- Tradeoff noted: reply is sent as one `text` chunk (ConversationRelay speaks it, interruptible at the audio layer) rather than per-token streaming; sufficient for interruptibility. Per-token streaming is a future refinement.

## Still TODO (user roadmap from message 507)
- **T3 (P1)** Synced transcript playback + real call recordings.
- **T4 (P1)** Auto-dial mode (continuously dial the campaign queue).
- ~~T5 Fully editable campaigns~~ ✅ DONE (iteration 17)
- ~~T6 Campaign lead add/remove~~ ✅ DONE (iteration 17); more filters still open (P2).
- **T7 (P2)** Email provider (Gmail/O365 OAuth) + SMS section/campaigns in Settings.
- ~~T8 Provider balances in Settings~~ ✅ DONE (iteration 17).
- ~~T9 CRM callback labels (AI vs Human)~~ ✅ DONE (iteration 17).
- ~~T10 Remove AI System Prompt from Org Settings~~ ✅ DONE (user removed; confirmed absent).
- **Refactor**: split `routes.py` and the large page components (Campaigns.jsx, Leads.jsx) into modules.

## Iteration 22 (2026-07-14) — Security audit remediation
Audit verdict was FAIL (1 Critical, 2 High, 1 Medium). Fixes applied (nothing required from the user; demo logins & live calls unaffected):
- **SEC-002 (High) — secret leakage** FIXED: `GET /api/settings/org` (available to ALL roles) was returning the org record incl. `integrations` (Twilio/ElevenLabs/LLM/O365 secrets). Now excludes `integrations`; secrets remain admin-only via `/settings/integrations`. Verified: response no longer contains `integrations`.
- **SEC-001 (Critical) — default owner/admin creds + self-reset** FIXED: removed the on-boot password reset in `auth.py` (`seed_admin`/`seed_owner`) — seed now only *creates* accounts if absent, so a customer-changed password persists; env `OWNER_PASSWORD`/`ADMIN_PASSWORD` still override on first seed. Also removed the **public demo-credential hints** from the login page (`Login.jsx`). ⚠️ Demo defaults (Owner123!/Admin123!) still exist so nothing breaks — recommend changing them in-app (now persists) before real launch.
- **SEC-003 (High) — unauth Twilio webhooks** FIXED: added `X-Twilio-Signature` HMAC-SHA1 validation (`twilio_voice.validate_twilio_request`, deterministic URL from `public_base_url()`) on `/relay/voice`, `/relay/incoming`, `/voice`, `/turn`, `/status`; **fail-open when no Twilio auth token is configured** (preview unaffected) and enforces (403) when a token is set. Env kill-switch `TWILIO_VALIDATE_SIGNATURE` (default on). Added per-IP rate limiting (20/min) on `/relay/incoming`. Verified: valid sig→pass, forged/missing→reject, no-token→open, limiter trips.
- **SEC-004 (Medium) — CORS wildcard** FIXED: `server._cors_origins()` now ignores a `*` value and builds an allowlist (frontend origin from `public_base_url()` + localhost; override via `CORS_ORIGINS`). Verified: evil origin blocked, frontend origin allowed, login 200, no console CORS errors.
- **Low** — removed commented hardcoded ElevenLabs key in `integrations.py`.
- **ACTION FOR USER**: the previously-committed ElevenLabs key `sk_9a35…` is in git history — **rotate it in the ElevenLabs dashboard**.
- Deferred (breakage risk / by design): JWT→httpOnly-cookie migration, per-account login throttle (current IP+email lockout kept to avoid victim lockout), call-control permission tightening.
- **Tunable parameters in Settings → Integrations** (persist + merge-safe): **ElevenLabs** TTS model (Flash/Turbo/Multilingual) + stability, similarity, style, speed sliders; **LLM** model, temperature slider, max reply length (1–4 sentences), and sentence-chunking toggle. `generate_tts` re-enabled `VoiceSettings` (was commented out); `_chat`/`stream_agent_reply` apply temperature via `with_params`.
- **Natural chunking of long replies**: ConversationRelay buffers streamed tokens into complete sentences before sending to Twilio TTS (verified: a "tell me everything" prompt returned 2 clean sentences, capped by max_sentences). Toggle via `llm_chunking`.
- **ElevenLabs credit auto-shown**: Settings balances now auto-load on open (no button click); shows EL characters left + Twilio balance when keys set, 3CX/LLM informational.
- **Voice-optional test calls**: Test Calls voice dropdown has **'No voice (text only)'** (first, no phantom blank option); starting with no voice runs text-only; the **AI model in use is shown** in diagnostics (from start response `llm_model`).
- **Live Calls page removed**; folded into the Call action: pressing **Call** on a lead shows a **'Listen in'** checkbox → opens a `CallMonitor` dialog with the real-time transcript + a **'Take over'** button (intentionally not wired yet — shows an info toast).
- Verified: iteration_16.json — **frontend E2E 100%** incl. the merge regression (twilio_account_sid preserved); backend params/chunking/model-display curl+WS-verified. Fixed 2 minor polish items (duplicate empty option, `<option>` child warning) post-report.
- **Root cause of remaining latency**: (1) cold-start penalty — the FIRST LLM request per call paid the TLS/connection setup cost (~1.4–4s); (2) 3 sequential DB round-trips on the hot path before the LLM started each turn; (3) unbounded reply length.
- **Fixes (all in `conversation_relay.py`)**:
  - **Connection warmup** — on ConversationRelay `setup`, a tiny throwaway LLM request warms the connection pool *while the caller is still hearing the greeting*, so the first real turn is warm.
  - **Context cached on the WebSocket** — call + org (with system prefix) + transcript loaded ONCE on setup; zero DB reads before the LLM on each turn; transcript persisted off the hot path.
  - **Brief replies** — `stream_agent_reply(..., brief=True)` instructs one/two short sentences for live calls (fast to generate + speak).
  - Fixed a Motor `asyncio.create_task` bug (Motor returns a Future here) that was crashing the WS on setup.
- **Measured (via WS, gpt-4o, realistic greeting delay)**: **first-token 0.48s** on the very first call, ~0.59s after — genuinely sub-1s. (Total caller-stop→AI-speaks ≈ 1–1.5s incl. Twilio's own STT endpointing.)
- **Turn-based mode removed** — all Twilio calls now use ConversationRelay streaming (`_twilio_webhooks` always returns the relay URL); the Settings voice-mode toggle is gone.
- **Stable inbound webhook added**: `POST /api/telephony/twilio/relay/incoming` builds an AI call on the fly (org resolved by the dialed number) and connects it to the streaming agent. Surfaced + copyable in Settings → Integrations for pasting into the Twilio Console (Number → Voice → "A call comes in").
- Verified server-side (warm TTFT, incoming TwiML, streaming chunks, interrupt handling). Live phone audio to confirm on deploy.
- **Confirmed the streaming WebSocket is reachable through the ingress** (external `wss://…/api/telephony/twilio/relay/ws/{id}` handshake upgrades OK) — so ConversationRelay (sub-1s) is viable here. Calls stuck at ~10s were running the turn-based `<Gather>` fallback.
- **`<Gather>` fallback heavily optimised** (`twilio_voice.py`): (1) the AI prompt is now nested INSIDE `<Gather>` → the prospect can **barge in / talk over the AI** (natural interruption); (2) TTS uses the fast `eleven_flash_v2_5` model; (3) synthesised audio is stored in **MongoDB (`tts_audio`) instead of in-process memory** and served from there — fixes multi-second Twilio retry delays / 404s on horizontally-scaled deploys (a prime suspect for the 10s); (4) `speechModel="experimental_conversations"` + `actionOnEmptyResult` for snappier, conversational turn-taking; audio is freed on call completion.
- **Sub-1s recipe (surfaced in Settings)**: use **Real-time streaming** voice mode (default; this is the webhook Twilio connects to for streaming) + a fast model. Measured stream time-to-first-token: GPT-4o ≈0.5s, GPT-4.1-mini ≈0.4s (sub-1s); Claude ≈1.2s.
- Verified: WSS reachable externally; both webhooks render correct TwiML; Mongo audio serve returns 200/audio-mpeg; streaming WS still emits incremental chunks. Live phone-audio latency to be confirmed on the user's deployed call.

## Iteration 18 (2026-07-13) — Live-call latency fix: token-streamed AI voice (sub-1s)
- **Problem**: live calls took ~10s to respond (text test calls were <1s). Root cause: the voice path `await`ed the FULL LLM reply (~1.7s) before any audio, then synthesised the whole reply with the slow `eleven_multilingual_v2` model, plus `<Gather>` endpointing — compounding to ~10s.
- **Fix (core)**: ConversationRelay now **streams LLM tokens** to Twilio as they arrive (`integrations.stream_agent_reply` via `LlmChat.stream_message` → `TextDelta`). The AI starts speaking on the **first token** instead of after the full reply. Verified: WS emits multiple incremental `text` chunks + final `last:true`; first chunk ~1.2s (Claude) and continuous thereafter.
- **Fix (gather fallback)**: `generate_tts` gained a `model` override; the turn-based path now uses the fast **`eleven_flash_v2_5`** model instead of `multilingual_v2`.
- **Model guidance (measured TTFT via streaming)**: GPT-4o ≈ 0.52s, GPT-4.1-mini ≈ 0.40s (**sub-1s**); Claude Sonnet/Haiku ≈ 1.2s. Settings → Integrations now tells users: for sub-1s pick Real-time streaming voice mode **and** a fast OpenAI model in the AI Language Model section.
- To benefit: org must use **Real-time streaming** voice mode (default) — verify on deployed env (ConversationRelay needs public WSS).
- **T5 Editable campaigns**: campaign cards now have an **Edit** (pencil) button → dialog to edit name/description/audience/script/voice/schedule, saved via existing `PUT /api/campaigns/{id}`.
- **T6 Add/remove leads**: edit dialog supports switching audience to **Specific clients** with an add/remove lead picker. New backend `POST /api/campaigns/{id}/leads {contact_ids, action: add|remove}` (sets audience='specific', updates contact_ids).
- **T8 Credits & balances**: new `GET /api/settings/integrations/balances` fetches live remaining credit — **ElevenLabs** characters (v1/user/subscription), **Twilio** account balance (Balance.json); 3CX & LLM shown as informational (no public balance API). Settings → Integrations shows a **Credits & balances** section with a "Check balances" button.
- **T9 CRM callback labels**: `ContactUpdate` gained `callback_at` + `callback_type` (ai|human). Leads table has a new **Callback** column (date + AI/Human badge); the lead detail sheet has a **Schedule callback** section (datetime + AI/Human toggle + Save).
- **T10**: confirmed the **AI System Prompt** section is gone from Organisation Settings (user removed it; verified absent).
- Verified: iteration_15.json — **frontend E2E 100%**, all backend endpoints curl-verified. No bugs.

## Iteration 23 (2026-08-05) — CRM CSV import + Gemini default + test-call analytics exclusion
- **CRM CSV import** (`POST /api/contacts/import`, multipart): imports HubSpot-style lead CSVs. Header map covers First/Last Name, Mobile Phone, Email, Company/Account, Lead Notes, Lead Status, Lead Owner, Lead Owner Alias, Lead Source, HS-Traffic-Category, Created/Last-Activity/Last-Contacted dates (utf-8-sig/latin-1, 10 MB cap). **Always creates a new contact** (never merges) and flags matches on normalized phone/email as `is_potential_duplicate` with a reason; rows missing a phone are skipped; DNC matches import as opted-out. Returns created/duplicates/skipped/errors/mapped_columns. Extra columns stored as dedicated contact fields (lead_status, lead_owner, lead_owner_alias, lead_source, hs_traffic_category, lead_created_date, last_activity_date, last_contacted_date) — nothing dumped into notes.
  - **Leads.jsx**: new **Import CSV** button (hidden file input) + result toast; table gained **Owner** and **Source** columns and a **DUP** badge; detail sheet shows all imported fields + a "Potential duplicate" banner. Verified: import (created 3/skipped 1), re-import flags 3 dups, UI renders badges/columns (screenshot).
- **Gemini default = `gemini-2.5-flash-lite`**: reordered `LLM_MODELS['gemini']` (flash-lite first) + `DEFAULT_MODEL['gemini']`. Gemini already fully wired (Settings provider dropdown, `/llm/models`, `_chat`/`stream_agent_reply` via emergentintegrations LlmChat `.with_model('gemini', ...)`) and works with BOTH the Emergent Universal key and a BYO `gemini_api_key`. Flash + Flash-Lite selectable.
- **Test calls excluded from analytics everywhere** (`is_test != True`): dashboard `total_calls`/rates/timeline (`/dashboard/stats`), campaign analytics (`_campaign_calls`), and per-contact `call_count`/last-call fields in `/contacts`. Verified: demo org has 31 calls (26 test) → dashboard now reports 5.

## Iteration 24 (2026-08-05) — Fix: ElevenLabs voice on live Twilio calls (ConversationRelay)
- **Root cause**: live calls use ConversationRelay (`conversation_relay.py`), which was only mapping the selected voice to a **Google en-GB built-in Twilio TTS** voice — the ElevenLabs voice ID was never sent. Previews use ElevenLabs directly, hence they sounded right while live calls fell back to a "standard" voice.
- **Fix**: `_relay_twiml` now emits `ttsProvider="ElevenLabs"` + `voice="<elevenlabs_voice_id>-<model>-<speed_stability_similarity>"` (+ `elevenlabsTextNormalization="on"`) whenever the org has a valid, enabled ElevenLabs key (`select_tts_provider` == elevenlabs). Reuses the SAME `elevenlabs_voice_id` from `VOICE_CATALOG` as previews, maps the org's ElevenLabs model to CR model ids (flash_v2_5/turbo_v2_5/…; default flash_v2_5), applies per-voice speed/stability + integ similarity. Falls back to Google en-GB only when ElevenLabs is absent/disabled. Both `/relay/voice` (outbound) and `/relay/incoming` (inbound) pass the org through. Verified via TwiML render for active/absent/disabled cases.
- **⚠️ Deploy prerequisite**: Twilio ConversationRelay's ElevenLabs provider needs ElevenLabs enabled on the Twilio account (add your ElevenLabs API key in the Twilio Console → Voice → ConversationRelay/BYOK) so Twilio can authenticate to ElevenLabs. Confirm on a live deployed call.

## Iteration 25 (2026-08-05) — End-call button + automatic voicemail detection/tagging
- **Voicemail auto-detect + auto-end**: outbound Twilio calls now start with async Answering Machine Detection (`MachineDetection=Enable`, `AsyncAmd=true`, `AsyncAmdStatusCallback`) — humans connect with zero added latency. New webhook `POST /api/telephony/twilio/amd/{call_id}` (signature-validated): when `AnsweredBy` is `machine_*`/`fax`, it tags the call `voicemail=True`, `outcome="voicemail"`, sets status `completed`, appends a system transcript note, and **hangs up the call automatically** (`twilio_hangup_call`). Verified end-to-end (simulated AMD → call tagged + completed).
- **End call button**: `CallMonitor` now has a red **End call** button → `POST /api/calls/{id}/hangup`; reloads the CRM on end. Fixed a latent bug — hangup/takeover checked only `provider_call_sid` (set on inbound), so outbound calls couldn't be ended; now `dial_contact`/`campaign_dial_next` also store `provider_call_sid` and both endpoints fall back to `callid`.
- **Voicemail tag UI**: orange **Voicemail** badge in the CallMonitor header and in each CRM call-history card.
- Frontend threading: `twilio_make_call`/`place_outbound_call` gained an `amd_url` param; `_twilio_webhooks` returns a 3-tuple (voice/status/amd).

## Iteration 26 (2026-08-05) — Campaign auto-dial mode + no-answer/voicemail not rated
- **Auto-dial mode**: `POST /campaigns/{id}/auto-dial/start` launches an in-process background loop (`_auto_dial_loop`) that dials the next queued lead, waits for the call to reach a terminal state (`_wait_for_call_end`), then dials the next — the AI (ConversationRelay) talks to each answered lead. Stops automatically on empty queue, outside calling hours, or provider/dial error (reason persisted on `campaign.auto_dial`). `POST .../stop` and `GET .../status` added. Start validates provider enabled + calling hours + non-empty queue. Frontend: **Start/Stop auto-dial** panel in the campaign Queue sheet with a live pulsing indicator, reason text, and 3s status polling (manual "Dial next" disabled while active). Verified: start→loop runs→self-stops gracefully with a clear reason on dial failure; status/stop work. ⚠️ Loop is per-worker in-memory — it stops if the backend restarts (resume by pressing Start again).
- **No-answer / voicemail not rated**: calls that aren't answered by a human are marked `status="no_answer"` and are **never analysed/rated**. Rule applied in both finalisers: `conversation_relay._finalise` (rates only if a `prospect` turn exists and not voicemail) and `twilio_voice.status_cb` (rates only on `completed` + answered + not voicemail; `busy`/`no-answer`/`failed`/`canceled` → `no_answer`). AMD voicemail now sets `status="no_answer"`, `outcome="voicemail"`. UI: "No answer"/"Voicemail" badges in the CRM call history and the campaign Called list (instead of a rating). Verified: voicemail (AMD) and unanswered (status callback) both end as `no_answer` with no rating/analysis.

## Iteration 27 (2026-08-06) — STT accuracy, call-ending behaviour, more voices + custom voice ID
- **Better speech recognition (STT)**: `_relay_twiml` now sends ConversationRelay STT tuning — `hints` (brand name + common cold-call phrases like "not interested / tell me more / how much / call me back / remove me"), `ignoreBackchannel="true"` (ignores "yeah/uh-huh" so they don't trigger turns), and `interruptSensitivity="medium"` (fewer false interrupts from noise). Removed `reportInputDuringAgentSpeech` (default `none`) so the agent isn't fed partial/echo speech. Verified in rendered TwiML.
- **Calls no longer end randomly**: ending logic now fires ONLY when the **agent's reply** contains a clear sign-off (`AGENT_CLOSE`: goodbye / have a great day / thanks for your time / take care …) OR the **prospect explicitly opts out** (`OPTOUT_HINTS`). Previously it matched close words in the prospect's speech (and STT noise), causing premature hang-ups.
- **More ElevenLabs voices**: added 6 (Rachel, Domi, Elli, Adam, Antoni, Josh) → 12 total in `VOICE_CATALOG`. Verified in `/api/voices` and the Test Calls picker.
- **Custom ElevenLabs Voice ID**: new Settings → Integrations fields (`elevenlabs_custom_voice_id` / name / gender). `get_voice(voice_id, org)` resolves `"custom"`; it appears as **"Custom voice"** in `/api/voices` and flows through previews, `generate_tts`, and ConversationRelay (`_relay_tts`). Verified end-to-end via API (save → appears with pasted ID).
- ⚠️ Live-call STT/ending improvements can only be fully confirmed on a real deployed Twilio call.
