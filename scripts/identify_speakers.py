#!/usr/bin/env python3
"""
identify_speakers.py — Re-label speakers in a transcription transcript using the
voiceprint library, via the gateway endpoint /api/transcription/identify_from_file.

Typical usage
-------------

  # Run identification against an audio file and a voiceprints JSON:
  ./identify_speakers.py \
      --audio /path/to/audio.mp3 \
      --voiceprints voiceprints.json

  # Apply the identification result to an existing transcript JSON,
  # overwriting it in-place (a .bak copy is kept):
  ./identify_speakers.py \
      --audio /path/to/audio.mp3 \
      --voiceprints voiceprints.json \
      --transcript /path/to/transcript.json \
      --apply

  # Limit identification to a [start, end] timeframe (seconds):
  ./identify_speakers.py \
      --audio /path/to/audio.mp3 \
      --voiceprints voiceprints.json \
      --start 12.5 --end 90 \
      --transcript transcript.json --apply

voiceprints.json format
-----------------------

Either the raw localStorage `PIN_VOICEPRINTS` array exported from the UI:

    [
      {"label": "Marco_Tulio", "voiceprint": "<base64>", ...},
      ...
    ]

or a wrapped object: {"voiceprints": [...]}.
Only `label` and `voiceprint` are sent to the API.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

DEFAULT_BASE = os.environ.get(
    "transcription_GATEWAY_BASE",
    "https://www.awareness-ai.com.br",
).rstrip("/")
ENDPOINT = "/api/transcription/identify_from_file"


def load_voiceprints(path: Path) -> List[Dict[str, str]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "voiceprints" in raw:
        raw = raw["voiceprints"]
    if not isinstance(raw, list):
        raise SystemExit(f"voiceprints file must contain a list, got {type(raw).__name__}")
    out: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label", "")).strip()
        vp = item.get("voiceprint")
        if label and vp:
            out.append({"label": label, "voiceprint": vp})
    if not out:
        raise SystemExit("no usable voiceprints (need objects with 'label' and 'voiceprint')")
    return out


def call_identify(
    base_url: str,
    audio_path: Path,
    voiceprints: List[Dict[str, str]],
    api_key: Optional[str],
    confidence: Optional[float],
    timeout: int,
) -> Dict[str, Any]:
    url = base_url + ENDPOINT
    files = {"file": (audio_path.name, audio_path.open("rb"), "application/octet-stream")}
    data: Dict[str, str] = {"voiceprints": json.dumps(voiceprints)}
    if api_key:
        data["api_key"] = api_key
    if confidence is not None:
        data["confidence"] = str(confidence)
    print(f"[identify] POST {url}  (audio={audio_path.name}, voiceprints={len(voiceprints)})", file=sys.stderr)
    t0 = time.time()
    try:
        resp = requests.post(url, files=files, data=data, timeout=timeout)
    finally:
        files["file"][1].close()
    dt = time.time() - t0
    print(f"[identify] HTTP {resp.status_code}  in {dt:.1f}s", file=sys.stderr)
    if not resp.ok:
        sys.stderr.write(resp.text[:2000] + "\n")
        resp.raise_for_status()
    return resp.json()


def filter_turns_by_window(
    turns: List[Dict[str, Any]],
    start: Optional[float],
    end: Optional[float],
) -> List[Dict[str, Any]]:
    if start is None and end is None:
        return turns
    s = -float("inf") if start is None else float(start)
    e = float("inf") if end is None else float(end)
    out: List[Dict[str, Any]] = []
    for t in turns:
        ts = float(t.get("start", 0.0) or 0.0)
        te = float(t.get("end", ts) or ts)
        # Overlap test
        if te < s or ts > e:
            continue
        out.append(t)
    return out


def best_label_per_speaker(
    segments: List[Dict[str, Any]],
    turns: List[Dict[str, Any]],
    window: Tuple[Optional[float], Optional[float]],
) -> Dict[str, str]:
    """Return mapping {raw_speaker -> best_match_label} via max time-overlap."""
    ws, we = window
    ws_v = -float("inf") if ws is None else float(ws)
    we_v = float("inf") if we is None else float(we)
    scores: Dict[str, Dict[str, float]] = {}
    for seg in segments:
        spk = seg.get("speaker")
        if not spk:
            continue
        s_start = float(seg.get("start", 0.0) or 0.0)
        s_end = float(seg.get("end", s_start) or s_start)
        # Clip segment to window
        s_start = max(s_start, ws_v)
        s_end = min(s_end, we_v)
        if s_end <= s_start:
            continue
        bucket = scores.setdefault(spk, {})
        for turn in turns:
            label = turn.get("match_label")
            if not label:
                continue
            t_start = float(turn.get("start", 0.0) or 0.0)
            t_end = float(turn.get("end", t_start) or t_start)
            overlap = max(0.0, min(s_end, t_end) - max(s_start, t_start))
            if overlap <= 0:
                continue
            bucket[label] = bucket.get(label, 0.0) + overlap
    out: Dict[str, str] = {}
    for spk, by_label in scores.items():
        if not by_label:
            continue
        best = max(by_label.items(), key=lambda kv: kv[1])
        out[spk] = best[0]
    return out


def apply_to_transcript(
    transcript_path: Path,
    speaker_labels: Dict[str, str],
    keep_backup: bool,
) -> Dict[str, Any]:
    blob = json.loads(transcript_path.read_text(encoding="utf-8"))
    # Backend stores either the legacy flat array or a dict {metadata, segments, ...}
    if isinstance(blob, list):
        wrapped = {"segments": blob, "metadata": {}}
    else:
        wrapped = blob
        wrapped.setdefault("segments", [])
        wrapped.setdefault("metadata", {})

    metadata = wrapped["metadata"] if isinstance(wrapped.get("metadata"), dict) else {}
    existing = metadata.get("speakerLabels") if isinstance(metadata.get("speakerLabels"), dict) else {}
    merged = dict(existing or {})
    merged.update(speaker_labels)
    metadata["speakerLabels"] = merged
    metadata["speaker_identification"] = {
        "applied_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "renamed": speaker_labels,
    }
    wrapped["metadata"] = metadata

    if keep_backup:
        backup = transcript_path.with_suffix(transcript_path.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(transcript_path, backup)
            print(f"[apply] backup -> {backup}", file=sys.stderr)

    transcript_path.write_text(
        json.dumps(wrapped, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[apply] updated {transcript_path}", file=sys.stderr)
    return wrapped


def main() -> int:
    ap = argparse.ArgumentParser(description="transcription speaker identification CLI")
    ap.add_argument("--audio", required=True, type=Path, help="Audio file to analyse")
    ap.add_argument("--voiceprints", required=True, type=Path, help="Voiceprints library JSON")
    ap.add_argument("--transcript", type=Path, help="Existing transcript JSON to apply labels to")
    ap.add_argument("--apply", action="store_true", help="Write speakerLabels back to transcript")
    ap.add_argument("--start", type=float, default=None, help="Window start (seconds)")
    ap.add_argument("--end", type=float, default=None, help="Window end (seconds)")
    ap.add_argument("--api-key", default=os.environ.get("PYANNOTE_API_KEY"), help="Pyannote API key (else uses gateway env)")
    ap.add_argument("--confidence", type=float, default=None, help="Match confidence threshold (0-1)")
    ap.add_argument("--base-url", default=DEFAULT_BASE, help=f"Gateway base URL (default {DEFAULT_BASE})")
    ap.add_argument("--timeout", type=int, default=900, help="HTTP timeout seconds")
    ap.add_argument("--no-backup", action="store_true", help="Do not write transcript .bak before --apply")
    ap.add_argument("--out", type=Path, help="Write raw identification result JSON to this path")
    args = ap.parse_args()

    if not args.audio.is_file():
        ap.error(f"audio not found: {args.audio}")
    if not args.voiceprints.is_file():
        ap.error(f"voiceprints not found: {args.voiceprints}")
    if args.apply and not args.transcript:
        ap.error("--apply requires --transcript")
    if args.transcript and not args.transcript.is_file():
        ap.error(f"transcript not found: {args.transcript}")

    voiceprints = load_voiceprints(args.voiceprints)
    result = call_identify(
        base_url=args.base_url.rstrip("/"),
        audio_path=args.audio,
        voiceprints=voiceprints,
        api_key=args.api_key,
        confidence=args.confidence,
        timeout=args.timeout,
    )

    turns = result.get("turns") or []
    turns = filter_turns_by_window(turns, args.start, args.end)
    print(f"[identify] turns in window: {len(turns)}", file=sys.stderr)

    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[identify] raw result -> {args.out}", file=sys.stderr)

    if args.transcript:
        transcript = json.loads(args.transcript.read_text(encoding="utf-8"))
        segments = transcript.get("segments") if isinstance(transcript, dict) else transcript
        if not isinstance(segments, list):
            raise SystemExit("transcript JSON does not contain a 'segments' list")
        mapping = best_label_per_speaker(segments, turns, (args.start, args.end))
        print("[map] speaker -> label:", file=sys.stderr)
        for k, v in mapping.items():
            print(f"  {k} -> {v}", file=sys.stderr)
        if args.apply and mapping:
            apply_to_transcript(args.transcript, mapping, keep_backup=not args.no_backup)
        elif args.apply:
            print("[apply] no matches; nothing to do", file=sys.stderr)

    # Print a compact summary on stdout
    json.dump(
        {
            "job_id": result.get("job_id"),
            "media_url": result.get("media_url"),
            "turns_total": len(result.get("turns") or []),
            "turns_in_window": len(turns),
            "window": {"start": args.start, "end": args.end},
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
