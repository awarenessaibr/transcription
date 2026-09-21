#!/bin/bash
# Ingest the 112 missing (ACHR.md 83 + TOKYO_1963.md 29) into all 3 collections,
# prune the 33 orphans (ACHR_1969.md 30 + Chicago_1944.md 3), then regenerate.
# Backups: /tmp/orphan_backup_2/ (payloads) + /tmp/registry_backup/
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"

# 1) Real ingest — canonical (dense) + local (384-dim embeddings) + bm25 (sparse).
#    --prune-orphans deletes points whose ELIs are no longer in data/law.
PYTHON="$PWD/.venv-py312/bin/python"

# 1) Real ingest — canonical (dense) + local (384-dim embeddings) + bm25 (sparse).
#    --prune-orphans deletes points whose ELIs are no longer in data/law.
"$PYTHON" scripts/ingest_law_corpus.py ingest \
  --target both --prune-orphans --allow-new

# 2) Regenerate the registry artifacts from the now-converged collections.
"$PYTHON" scripts/ingest_law_corpus.py validate --write-registry

# 3) Confirm convergence.
"$PYTHON" -c "
from src.config import settings
from src.infrastructure.qdrant_law_index import build_qdrant_client
c = build_qdrant_client(settings.QDRANT_URL, settings.QDRANT_API_KEY)
for coll in (settings.LAW_COLLECTION, settings.LAW_BM25_COLLECTION, settings.LAW_LOCAL_COLLECTION):
    n = c.count(collection_name=coll, exact=True).count
    print(f'  {coll:24s} {n} points')
"
