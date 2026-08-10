# Line-Ups Game

Starter scaffold for the Line-Ups-Game project. This branch provides a minimal FastAPI backend and initial database schema so you can continue development (for example, using your Claude Code subscription to expand features).

What is included
- backend/: minimal FastAPI app with two endpoints (/api/health, /api/metadata) and DB connection placeholder
- db/schema.sql: initial Postgres schema for matches, teams, players, appearances, games and hints
- .gitignore

How to run (local, minimal):
1. Create a Python virtualenv and install dependencies:
   python -m venv venv
   source venv/bin/activate
   pip install -r backend/requirements.txt

2. Provide a DATABASE_URL env variable for Postgres (optional for now). Run dev server:
   uvicorn backend.app.main:app --reload --port 8000

3. Open http://localhost:8000/api/health and /api/metadata

Next steps you can do with Claude Code (examples):
- Expand the API endpoints (search, game creation, guessing, hint generation)
- Implement full SQLAlchemy models and Alembic migrations using db/schema.sql
- Implement Wikipedia ingestion script to seed matches and appearances
- Add auth, Redis session store, and frontend scaffolding

If you want a different stack (Node/Express) or TypeScript, tell me and I can scaffold that instead.
