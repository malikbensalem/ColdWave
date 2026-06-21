# Changelog

## [1.1.0] — 2026-06-21
Five feature areas added without breaking existing functionality.

### Added
- **One-command local startup**: `./start.sh` / `make dev` start backend + frontend together with dependency + env validation, MongoDB reachability check, health URLs, and graceful shutdown. New `Makefile`, `start.sh`, `backend/.env.example`, `frontend/.env.example`. New `GET /api/health`.
- **WhatsApp messaging** (Meta Cloud API) with provider abstraction (`WhatsAppCloudProvider` / `MockWhatsAppProvider`), outbound send with **retries + timeouts + dead-letter logging**, inbound + delivery-status **webhook with X-Hub-Signature-256 verification** and verify-token handshake, message lifecycle (queued/sent/delivered/failed/received), per-org **rate limiting**, DNC protection, and **PII-redacted logs**. New Messaging page + `/messaging` nav.
- **ElevenLabs fix**: deterministic `select_tts_provider` + `generate_tts`; test calls now actually use ElevenLabs (voice id, model, stability/similarity/style applied) with diagnostic logs and **no silent fallback**. New **Validate key** endpoint/button (immediate valid/invalid feedback). Voice settings in Settings; per-call diagnostics panel.
- **Audit log**: append-only `record_audit` carrying actor, action, entity, before/after **diff**, **source IP**, **UTC timestamp**, **correlation id** (set by request middleware). Secrets masked. New `GET /api/audit` with actor/entity/action/date filters + Settings → Audit viewer.
- **Knowledge-base opening mode**: scripted vs KB-guided openings generated from per-workspace KB (paste + `.pdf`/`.txt` upload) with brand/compliance + profanity guardrails and reliable fallback to scripted. Settings → Opening & KB controls (mode, creativity, max length).

### Changed
- `IntegrationSettings` extended (ElevenLabs voice settings, WhatsApp creds). Org gains `opening_mode/creativity/max_length`.
- CRM/script/campaign mutations now emit rich audit entries.

### Tests
- New `backend/tests/` (pytest): TTS selection + ElevenLabs path (regression guard against silent fallback), messaging provider + PII masking, audit diff/masking, KB guardrails. `make test`.

### Migration / rollout notes
- **No destructive migration.** New collections (`messages`, `message_dead_letters`, `kb_entries`) and indexes are created on startup. Existing orgs get opening-mode defaults lazily (defaults applied in code; new orgs seed them).
- Add new env keys from `backend/.env.example` (all optional except core). Restart backend after `.env` changes.
- Rollback: revert to previous build; new collections are additive and safe to leave in place.

### Known limitations
- SMS intentionally not implemented (WhatsApp only, per request).
- Office 365 SSO remains config-only.
- KB retrieval is keyword/recency based (no vector search yet).
- AI features depend on Emergent LLM key budget.
