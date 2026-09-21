# Step 2 — Ingest blocked (2026-09-19)

- Alias map created: `data/law/_mapping/alias_map.json`
- 7 of 8 missing-article local files present (228, 229, 256, 257, 56, Constitucion, Prevaricacion); Art.224 covered inside Prevaricacion.md.
- `python scripts/ingest_law_corpus.py ingest --target local` failed: Qdrant server not reachable (`[Errno 61] Connection refused`).
- Action needed: start Qdrant (e.g. `docker-compose up qdrant` or the service defined in `docker-compose.yml`) then re-run ingest.
- Do NOT delete any local files; they are the only sources.
