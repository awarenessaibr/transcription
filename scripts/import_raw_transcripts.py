#!/usr/bin/env python3
"""Bulk-import LA8159 raw transcripts into data/transcripts/.

Reads every *.json under the raw incident directory, normalizes the two on-disk
schemas (``{content,audio_id}`` and ``{segments,transcript_id}``) into the internal
Transcript entity, and saves through JSONTranscriptStore.

Transcript id = file stem (e.g. ``aeropuerto_STG_20``), so the new id matches the
canonical naming used in ``transcripts_by_audio/`` and the rendered/ HTMLs.

Default is dry-run. Pass ``--apply`` to write.
Per file: skip if id already present in the store unless ``--overwrite`` is set.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.config import settings  # noqa: E402
from src.domain.entities.transcript import Segment, Speaker, Transcript  # noqa: E402
from src.infrastructure.json_store import JSONTranscriptStore  # noqa: E402

RAW_DEFAULT = Path(
    "/Users/leandrodisconzi/work/business/OliviaLegal/cases/INCIDENTS/"
    "INCIDENT_2024-07-05/transcripts/raw"
)


def _normalize(raw: dict, file_path: Path) -> Transcript:
    """Convert a raw JSON dict into a Transcript entity. Tolerant of mixed schemas."""
    tid = file_path.stem

    # Two segment-list shapes in the wild: "content" (raw narrative variant) or "segments" (whisper-like).
    items = raw.get("content")
    if not isinstance(items, list):
        items = raw.get("segments") or []

    segments: list[Segment] = []
    for i, seg in enumerate(items):
        # Index resolution: prefer explicit "id" (raw schema) or "index" (whisper schema); fall back to position.
        idx_raw = seg.get("id") if "id" in seg else seg.get("index", i)
        try:
            idx = int(idx_raw)
        except (TypeError, ValueError):
            idx = i

        speaker_label = (seg.get("speaker") or f"SPEAKER_{i:02d}").strip() or f"SPEAKER_{i:02d}"
        try:
            start = float(seg.get("start") or 0.0)
        except (TypeError, ValueError):
            start = 0.0
        try:
            end = float(seg.get("end") or start)
        except (TypeError, ValueError):
            end = start
        if end < start:
            end = start

        segments.append(
            Segment(
                index=idx,
                speaker=Speaker(label=speaker_label),
                start=start,
                end=end,
                text=str(seg.get("text") or ""),
            )
        )

    timestamp = raw.get("recordingdatetime") or raw.get("recordingDateTime") or ""
    metadata = {
        "title": raw.get("title", "") or "",
        "location": raw.get("location", "") or "",
        "imported_from": "raw_la8159",
        "raw_path": str(file_path),
    }
    if "audio_id" in raw and raw["audio_id"] != tid:
        metadata["raw_audio_id"] = str(raw["audio_id"])
    if "transcript_id" in raw and str(raw["transcript_id"]) != tid:
        metadata["raw_transcript_id"] = str(raw["transcript_id"])

    return Transcript(
        transcript_id=tid,
        segments=segments,
        source_file=str(file_path),
        language="es",
        metadata=metadata,
        timestamp=str(timestamp),
        provider="raw_la8159",
        original_transcript_id="",
    )


def run(raw_dir: Path, apply: bool, overwrite: bool, transcript_dir: Path) -> None:
    if not raw_dir.exists():
        print(f"[abort] missing raw dir {raw_dir}", file=sys.stderr)
        sys.exit(2)

    files = sorted(raw_dir.glob("*.json"))
    if not files:
        print(f"[abort] no *.json under {raw_dir}", file=sys.stderr)
        sys.exit(2)

    store = JSONTranscriptStore(str(transcript_dir))
    existing = set(store.list_ids())

    plans: list[tuple[Path, str, str, int]] = []  # (path, tid, action, n_segments)
    errors: list[tuple[Path, str]] = []

    for f in files:
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append((f, f"json: {e}"))
            continue
        try:
            t = _normalize(raw, f)
        except Exception as e:
            errors.append((f, f"normalize: {e}"))
            continue
        action = "import"
        if t.transcript_id in existing:
            action = "overwrite" if overwrite else "skip"
        plans.append((f, t.transcript_id, action, len(t.segments)))

    actions = {"import": 0, "overwrite": 0, "skip": 0}
    for _, _, a, _ in plans:
        actions[a] += 1
    print(
        f"[plan] raw_dir={raw_dir}  store={transcript_dir}  files={len(files)}  "
        f"import={actions['import']}  overwrite={actions['overwrite']}  skip={actions['skip']}  "
        f"errors={len(errors)}"
    )
    for f, tid, action, nseg in plans:
        marker = {"import": "+", "overwrite": "~", "skip": "."}[action]
        print(f"  {marker} {tid:50s}  segs={nseg:>4}  ({f.name})")
    for f, msg in errors:
        print(f"  ! {f.name}: {msg}", file=sys.stderr)

    if not apply:
        print("\n[dry-run] nothing written. Re-run with --apply to write.")
        return

    written = 0
    for f, tid, action, _ in plans:
        if action == "skip":
            continue
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            t = _normalize(raw, f)
            store.save(t)
            written += 1
        except Exception as e:
            errors.append((f, f"save: {e}"))

    print(f"\n[done] written={written}  errors={len(errors)}")
    if errors:
        for f, msg in errors:
            print(f"  ! {f.name}: {msg}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    ap.add_argument("--store", type=Path, default=Path(settings.TRANSCRIPT_DIR))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()
    run(
        raw_dir=args.raw,
        apply=args.apply,
        overwrite=args.overwrite,
        transcript_dir=args.store,
    )


if __name__ == "__main__":
    main()
