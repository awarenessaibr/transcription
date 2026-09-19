#!/usr/bin/env python3
"""Aggregate audit pass over every transcript in data/transcripts/.

Loads each transcript through the wired runtime and runs the structural
auditor. Prints totals by kind/severity, the noisiest files, and a
cross-corpus speaker-label drift report.

Useful as a baseline measurement before / after a refinement pass.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# Avoid loading torchaudio just for this read-only audit.
import os
os.environ.setdefault("ENABLE_ACOUSTIC_PROBES", "false")

from src.composition import build_runtime  # noqa: E402


def run(top_n: int) -> None:
    r = build_runtime()
    store = r.store_adapter
    auditor = r.auditor

    ids = sorted(store.list_ids())
    total = 0
    kind_totals: Counter[str] = Counter()
    sev_totals: Counter[str] = Counter()
    worst: list[tuple[int, str, dict]] = []
    clean = 0

    transcripts = []
    for tid in ids:
        t = store.load(tid)
        if t is None:
            continue
        transcripts.append(t)
        rep = auditor.audit(t)
        n = len(rep.anomalies)
        total += n
        for k, v in rep.kind_counts().items():
            kind_totals[k] += v
        for k, v in rep.severity_counts().items():
            sev_totals[k] += v
        if n == 0:
            clean += 1
        else:
            worst.append((n, tid, rep.kind_counts()))

    worst.sort(reverse=True)

    print(f"=== AGGREGATE AUDIT — {len(ids)} transcripts ===")
    print(f"Total anomalies: {total}")
    print(f"Clean files (0 anomalies): {clean} / {len(ids)}")
    print()
    print("By kind:")
    for k, v in sorted(kind_totals.items(), key=lambda x: -x[1]):
        print(f"  {k:30s} {v}")
    print()
    print("By severity:")
    for k, v in sorted(sev_totals.items(), key=lambda x: -x[1]):
        print(f"  {k:10s} {v}")
    print()
    print(f"Top {top_n} noisiest files:")
    for n, tid, by_kind in worst[:top_n]:
        sig = " ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
        print(f"  {n:>4}  {tid:50s}  {sig}")

    cross = auditor.audit_speaker_corpus(transcripts)
    print()
    print(f"Cross-corpus speaker drift clusters: {len(cross)}")
    for a in cross[:8]:
        print(f"   - {a.hint}")
    if len(cross) > 8:
        print(f"   ... ({len(cross) - 8} more)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    run(top_n=args.top)


if __name__ == "__main__":
    main()
