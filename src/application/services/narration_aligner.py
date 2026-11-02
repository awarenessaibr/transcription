"""Align source narration lines to Whisper's timestamped segments."""
from __future__ import annotations

import csv
import difflib
import io
import re
from dataclasses import dataclass

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")
_PAGE_MARKER = re.compile(
    r"^\s*p[áa]gina\s+([\w.-]+)\s*(?:[:\-–—,]\s*(.*))?$",
    re.IGNORECASE,
)
_EMPTY_TARGET_PENALTY = 1.5
_SEGMENT_STEP_PENALTY = 0.01
_INFINITY = float("inf")
_REVIEW_CONFIDENCE_THRESHOLD = 0.45


@dataclass(frozen=True)
class NarrationLine:
    text: str
    page: str


def _normalize(text: str) -> str:
    text = _PUNCTUATION.sub(" ", text.casefold())
    return _WHITESPACE.sub(" ", text).strip()


def text_similarity(left: str, right: str) -> float:
    """Return a blended character and token similarity score in [0, 1]."""
    left_norm, right_norm = _normalize(left), _normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    char_similarity = difflib.SequenceMatcher(None, left_norm, right_norm).ratio()
    left_words, right_words = set(left_norm.split()), set(right_norm.split())
    token_similarity = len(left_words & right_words) / len(left_words | right_words)
    return 0.6 * char_similarity + 0.4 * token_similarity


def parse_source_text(content: str) -> list[NarrationLine]:
    """Parse plain lines, page markers, or CSV with a ``text`` column."""
    content = content.lstrip("\ufeff")
    lines = content.splitlines()
    first_nonempty = next((line.strip() for line in lines if line.strip()), "")

    if first_nonempty:
        header = next(csv.reader([first_nonempty]))
        normalized_header = [column.strip().casefold() for column in header]
        if "text" in normalized_header:
            reader = csv.DictReader(io.StringIO(content))
            targets = []
            for row in reader:
                normalized_row = {
                    (key or "").strip().casefold(): value for key, value in row.items()
                }
                text = (normalized_row.get("text") or "").strip()
                if text:
                    targets.append(NarrationLine(
                        text=text,
                        page=(normalized_row.get("page") or "0").strip() or "0",
                    ))
            return targets

    targets = []
    page = "0"
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('"') and line.endswith('"') and len(line) > 1:
            line = line[1:-1]

        marker = _PAGE_MARKER.match(line)
        if marker:
            page = marker.group(1)
            spoken_text = (marker.group(2) or "").strip()
            if spoken_text:
                targets.append(NarrationLine(text=spoken_text, page=page))
            continue

        targets.append(NarrationLine(text=line, page=page))
    return targets


def align_lines_to_segments(
    targets: list[NarrationLine],
    segments: list[dict],
) -> list[tuple[int, int]]:
    """Assign each timed segment to a contiguous, monotonic target-line range."""
    target_count, segment_count = len(targets), len(segments)
    if target_count == 0:
        return []
    if segment_count == 0:
        return [(0, 0)] * target_count

    prefix_similarities: list[list[float]] = []
    for target in targets:
        prefix = [0.0]
        for segment in segments:
            prefix.append(prefix[-1] + text_similarity(target.text, str(segment["text"])))
        prefix_similarities.append(prefix)

    costs = [[_INFINITY] * (segment_count + 1) for _ in range(target_count + 1)]
    back = [[-1] * (segment_count + 1) for _ in range(target_count + 1)]
    costs[0][0] = 0.0

    for target_idx in range(target_count):
        prefix = prefix_similarities[target_idx]
        adjusted_prefix = [idx - score for idx, score in enumerate(prefix)]
        best_value, best_start = _INFINITY, -1

        for end in range(segment_count + 1):
            empty_cost = costs[target_idx][end] + _EMPTY_TARGET_PENALTY
            if empty_cost < costs[target_idx + 1][end]:
                costs[target_idx + 1][end] = empty_cost
                back[target_idx + 1][end] = end

            if end:
                start = end - 1
                if costs[target_idx][start] < _INFINITY:
                    candidate = costs[target_idx][start] - adjusted_prefix[start]
                    if candidate < best_value:
                        best_value, best_start = candidate, start
                if best_value < _INFINITY:
                    segment_cost = (
                        adjusted_prefix[end] + _SEGMENT_STEP_PENALTY + best_value
                    )
                    if segment_cost < costs[target_idx + 1][end]:
                        costs[target_idx + 1][end] = segment_cost
                        back[target_idx + 1][end] = best_start

    assignments: list[tuple[int, int]] = [(0, 0)] * target_count
    end = segment_count
    for target_idx in range(target_count, 0, -1):
        start = back[target_idx][end]
        if start < 0:
            start = end
        assignments[target_idx - 1] = (start, end)
        end = start
    return assignments


def build_aligned_rows(
    targets: list[NarrationLine],
    segments: list[dict],
    assignments: list[tuple[int, int]],
) -> list[dict]:
    """Build timestamped output rows and identify low-confidence matches."""
    resolved: list[tuple[float, float] | None] = [None] * len(targets)
    confidence: list[float] = [0.0] * len(targets)

    for idx, (start_idx, end_idx) in enumerate(assignments):
        if start_idx < end_idx:
            group = segments[start_idx:end_idx]
            resolved[idx] = (float(group[0]["start"]), float(group[-1]["end"]))
            recognized_text = " ".join(str(segment["text"]) for segment in group)
            confidence[idx] = text_similarity(targets[idx].text, recognized_text)

    for idx, timing in enumerate(resolved):
        if timing is not None:
            continue
        previous_end = 0.0
        for prev in range(idx - 1, -1, -1):
            previous_timing = resolved[prev]
            if previous_timing is not None:
                previous_end = previous_timing[1]
                break
        next_start = None
        for nxt in range(idx + 1, len(targets)):
            next_timing = resolved[nxt]
            if next_timing is not None:
                next_start = next_timing[0]
                break
        if next_start is None:
            next_start = previous_end + 0.5
        midpoint = (previous_end + next_start) / 2.0
        resolved[idx] = (midpoint, midpoint)

    rows = []
    previous_end = 0.0
    for target, timing, score in zip(targets, resolved, confidence, strict=True):
        assert timing is not None
        start, end = timing
        start = max(start, previous_end)
        end = max(start, end)
        previous_end = end
        rows.append({
            "start_ms": int(round(start * 1000)),
            "end_ms": int(round(end * 1000)),
            "page": target.page,
            "text": target.text,
            "confidence": round(score, 3),
            "needs_review": score < _REVIEW_CONFIDENCE_THRESHOLD,
        })
    return rows


def rows_to_csv(rows: list[dict]) -> str:
    """Serialize aligned rows using the agreed CSV columns."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["start_ms", "end_ms", "page", "text"])
    for row in rows:
        writer.writerow([row["start_ms"], row["end_ms"], row["page"], row["text"]])
    return output.getvalue()
