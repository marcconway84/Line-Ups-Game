A minimal CONTRIBUTING / next-steps file.

This scaffold was created to let you continue development using code-generation tools (e.g., Claude Code).

Suggested Claude tasks:
- Implement SQLAlchemy models for all schema tables in db/schema.sql and wire them into backend/app/db.py
- Add Alembic migrations configured for your Postgres instance
- Implement ingestion scripts that fetch match lineups from Wikipedia/Wikidata and insert appearances
- Add endpoints for search, games creation, guesses, and hint generation
- Add tests (pytest) and CI workflows
