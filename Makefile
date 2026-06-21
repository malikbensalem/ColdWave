.PHONY: dev install backend frontend test stop

# One-command local startup (backend + frontend together)
dev:
	@./start.sh

# Install all dependencies
install:
	cd backend && python3 -m pip install -r requirements.txt
	cd frontend && yarn install

# Run backend only
backend:
	cd backend && uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Run frontend only
frontend:
	cd frontend && yarn start

# Run backend test suite
test:
	cd backend && python3 -m pytest tests/ -v

# Stop stray dev processes
stop:
	-pkill -f "uvicorn server:app" || true
	-pkill -f "react-scripts start" || true
