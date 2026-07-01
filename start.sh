#!/usr/bin/env bash
# ColdWave — one-command local startup (backend + frontend)
# Usage: ./start.sh   (Ctrl+C stops both services gracefully)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[coldwave]${NC} $1"; }
ok()   { echo -e "${GREEN}[ok]${NC} $1"; }
warn() { echo -e "${YELLOW}[warn]${NC} $1"; }
die()  { echo -e "${RED}[error]${NC} $1" >&2; exit 1; }

# ---- 1. Dependency validation -------------------------------------------------
command -v python3 >/dev/null 2>&1 || die "python3 not found. Install Python 3.11+."
command -v node    >/dev/null 2>&1 || die "node not found. Install Node 18+."
command -v yarn    >/dev/null 2>&1 || die "yarn not found. Run: npm install -g yarn"
command -v mongod  >/dev/null 2>&1 || warn "mongod not on PATH — ensure MongoDB is running (MONGO_URL must be reachable)."

# ---- 2. Env validation --------------------------------------------------------
[ -f "$BACKEND_DIR/.env" ]  || die "Missing backend/.env. Copy backend/.env.example -> backend/.env and fill values."
[ -f "$FRONTEND_DIR/.env" ] || die "Missing frontend/.env. Copy frontend/.env.example -> frontend/.env and fill values."

REQUIRED_BACKEND_VARS=(MONGO_URL DB_NAME JWT_SECRET)
for v in "${REQUIRED_BACKEND_VARS[@]}"; do
  grep -qE "^${v}=" "$BACKEND_DIR/.env" || die "backend/.env is missing required var: ${v}"
done
grep -qE "^REACT_APP_BACKEND_URL=" "$FRONTEND_DIR/.env" || die "frontend/.env is missing REACT_APP_BACKEND_URL"
ok "Environment files validated."

# ---- 3. Install dependencies (first run) -------------------------------------
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  log "Installing frontend dependencies (first run)…"; ( cd "$FRONTEND_DIR" && yarn install --frozen-lockfile || yarn install )
fi
log "Ensuring backend dependencies…"; python3 -m pip install -q -r "$BACKEND_DIR/requirements.txt" --extra-index-url https://d33sy5i8bnduwe.cloudfront.net/simple/ || warn "pip install reported issues; continuing."

# ---- 4. Reachability of MongoDB ----------------------------------------------
MONGO_URL_VAL=$(grep -E "^MONGO_URL=" "$BACKEND_DIR/.env" | cut -d= -f2- | tr -d '"')
python3 - "$MONGO_URL_VAL" <<'PY' || die "Cannot reach MongoDB at MONGO_URL. Start MongoDB (e.g. 'mongod' or Docker) and retry."
import sys
try:
    from pymongo import MongoClient
    MongoClient(sys.argv[1], serverSelectionTimeoutMS=2500).admin.command("ping")
except Exception as e:
    print(e); sys.exit(1)
PY
ok "MongoDB reachable."

# ---- 5. Start services with graceful shutdown --------------------------------
PIDS=()
cleanup() {
  echo; log "Shutting down…"
  for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  ok "Stopped. Bye."
}
trap cleanup INT TERM

log "Starting backend on http://localhost:8001 …"
( cd "$BACKEND_DIR" && exec uvicorn server:app --host 0.0.0.0 --port 8001 ) &
PIDS+=($!)

log "Starting frontend on http://localhost:3000 …"
( cd "$FRONTEND_DIR" && exec yarn start ) &
PIDS+=($!)

sleep 3
echo -e "\n${GREEN}========================================${NC}"
echo -e "  ColdWave is starting up"
echo -e "  Backend  : http://localhost:8001/api/"
echo -e "  Frontend : http://localhost:3000"
echo -e "  Health   : curl http://localhost:8001/api/health"
echo -e "  Press Ctrl+C to stop both services"
echo -e "${GREEN}========================================${NC}\n"

wait
