# Step 3 — Drift resolution (local authoritative)

Drift ELIs (local file authoritative):
- CL.LPDC.T1.Art.3.b
- CL.LPDC.T1.Art.3.e
- CL.LPDC.Art.23
- CL.LPDC.Art.12
- CL.CPCL.C1.Art.269_ter

When Qdrant is available:
1. Delete Qdrant points for these ELIs.
2. Re-ingest local files (`python scripts/ingest_law_corpus.py ingest --target local`).
3. Re-run `python scripts/ingest_law_corpus.py validate --write-registry`.
