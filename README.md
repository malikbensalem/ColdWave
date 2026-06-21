# ColdWave — AI Cold Calling SaaS

Multi-tenant platform for compliant AI cold calling: AI voices (ElevenLabs), WhatsApp messaging, a CRM, test calls, UK/GDPR compliance, an append-only audit log, and a knowledge-base-guided opening mode.

---

## Prerequisites
- **Python** 3.11+
- **Node** 18+ and **Yarn** (`npm install -g yarn`)
- **MongoDB** running locally (or any reachable `MONGO_URL`)
- macOS / Linux / WSL2 (the one-command runner is a bash script)

## First-time setup
```bash
# 1. Clone, then copy env templates
cp backend/.env.example  backend/.env
cp frontend/.env.example frontend/.env

# 2. Edit backend/.env — set at minimum:
#    MONGO_URL, DB_NAME, JWT_SECRET, EMERGENT_LLM_KEY
#    (WhatsApp / ElevenLabs keys are optional — leave blank to run in mock mode)

# 3. (Optional) install deps up-front
make install
```

## One-command start (backend + frontend together)

### macOS / Linux / WSL2
```bash
./start.sh
# or
make dev
```

### Windows (10/11)
1. Install **Python 3.11+**, **Node 18+**, and Yarn (`npm install -g yarn`), and have **MongoDB** running (local service, Docker, or a MongoDB Atlas `MONGO_URL`).
2. Copy env templates: `copy backend\.env.example backend\.env` and `copy frontend\.env.example frontend\.env`, then edit `backend\.env`.
3. Double-click **`start.bat`** (or run it in a terminal).

`start.bat` validates Python/Node/Yarn + your `.env` files, checks MongoDB is reachable, installs frontend deps on first run, then opens the **backend** and **frontend** in two windows. Close those two windows to stop.

Either runner:
- validates dependencies (python3, node, yarn) and `.env` files with clear errors,
- verifies MongoDB is reachable,
- installs frontend deps on first run,
- starts the **backend** on http://localhost:8001 and **frontend** on http://localhost:3000,
- prints health URLs,
- shuts **both** down gracefully on `Ctrl+C`.

Health check: `curl http://localhost:8001/api/health`

Default seeded admin: **admin@coldwave.ai / Admin123!**

## Running tests
```bash
make test          # backend unit + integration tests (pytest)
```

---

## Feature configuration

### WhatsApp (Meta Cloud API)
Set in **Settings → Integrations → WhatsApp** (per workspace) or via env:
`WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`.
- Webhook URL to register with Meta: `{BACKEND}/api/webhooks/whatsapp`
- GET verify handshake uses `WHATSAPP_VERIFY_TOKEN`; POST verifies `X-Hub-Signature-256` with the app secret.
- With no credentials, WhatsApp runs in **mock mode** (messages progress queued→sent→delivered, no real send).

### ElevenLabs voices
**Settings → Integrations → ElevenLabs** → paste key → **Validate key** (tells you immediately if it’s valid/invalid) → enable.
When enabled with a valid key, **test calls use ElevenLabs audio** (model + stability/similarity/style applied). No silent fallback — if a configured key fails, the UI/logs show an explicit error.

### Opening line mode (scripted vs knowledge base)
**Settings → Opening & KB**: toggle mode, creativity, max length; add KB entries (paste or upload `.pdf`/`.txt`). In KB mode, openings are generated from the KB with brand/compliance guardrails, and **fall back to the scripted opening** if KB is empty or generation fails.

### Audit log
**Settings → Audit**: every create/update/delete and settings change is recorded append-only with actor, action, entity, before/after diff, **source IP**, **UTC timestamp**, and a correlation ID. Filter by actor / entity / action / date range.

---

## Common errors & fixes
| Symptom | Fix |
|---|---|
| `Missing required environment variables` | Copy `*.env.example` → `.env` and fill `MONGO_URL`, `DB_NAME`, `JWT_SECRET`. |
| `Cannot reach MongoDB at MONGO_URL` | Start MongoDB (`mongod` / Docker) or fix `MONGO_URL`. |
| `yarn not found` | `npm install -g yarn`. |
| Port 3000/8001 already in use | `make stop` (kills stray dev processes) then `./start.sh`. |
| AI features 500 / “budget” errors | Top up the Emergent LLM key (Profile → Universal Key → Add Balance). |
| WhatsApp “mock” badge | Add WhatsApp credentials in Settings → Integrations. |
| ElevenLabs preview uses browser voice | Validate + enable the key in Settings; ensure it returns “valid”. |
| Webhook returns 401 | Ensure `WHATSAPP_APP_SECRET` matches the Meta app; signature must be `sha256=…`. |

See `CHANGELOG.md` for rollout notes.
