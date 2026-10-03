"""Speaker-registry I/O: load curated profiles, resolve, and persist a mapping.

Responsibilities
----------------
* Parse the frontmatter of ``data/speakers/*.md`` (scalars **and** block lists:
  ``aliases`` and ``key_statements`` are what make deterministic resolution
  possible, and the pre-existing scalar-only parser silently dropped them).
* Join those profiles with the generated ``data/speaker_index.json``, which is
  what carries ``segment_labels`` and per-transcript appearances.
* Derive the evidence and the known cast for a transcript, hand both to
  :mod:`src.application.services.speaker_resolver`, and apply a confirmed
  mapping.
* Emit the consumable speaker+segment map (see
  :meth:`SpeakerRegistryStore.build_segment_map`).

Applying a mapping is deliberately conservative:
* it sets ``segment.speaker_id`` (the field added in the store round-trip fix)
  and leaves ``segment.speaker`` alone, so nothing downstream that keys on the
  raw/curated label breaks;
* it registers the raw label under the participant's ``segment_labels``, which
  is the bridge the existing index generator already understands — so the
  registry UI and ``speaker_index.json`` light up with no changes to them;
* it appends an auditable ``corrections_applied`` entry.

Nothing here auto-applies a proposal. Resolution is a suggestion; this module
only writes what a caller explicitly passes as a mapping.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import re
from dataclasses import replace
from pathlib import Path

from src.application.services.speaker_resolver import resolve_speakers
from src.domain.entities.transcript import Segment, Speaker, Transcript
from src.domain.speaker import (
    SpeakerEvidence,
    SpeakerProfile,
    SpeakerResolution,
)

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "1.0.0"

#: Frontmatter scalar: ``key: value`` at column 0.
_FM_SCALAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")
#: Frontmatter list item: ``  - value`` (optionally quoted).
_FM_ITEM_RE = re.compile(r"^\s+-\s+(.*)$")


def parse_frontmatter(text: str) -> dict:
    """Parse YAML-ish frontmatter into ``{key: str | list[str]}``.

    Handles the two shapes the speaker notes actually use: top-level scalars and
    top-level block lists. Nested mappings (``appearances:``) are skipped
    intentionally -- their authoritative form is ``speaker_index.json``.
    """
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}

    fm: dict[str, str | list[str]] = {}
    current_list: str | None = None
    for raw_line in match.group(1).splitlines():
        if not raw_line.strip():
            continue
        item = _FM_ITEM_RE.match(raw_line)
        if item and current_list:
            value = item.group(1).strip().strip('"').strip("'")
            if value:
                cast = fm.get(current_list)
                assert isinstance(cast, list)
                cast.append(value)
            continue
        scalar = _FM_SCALAR_RE.match(raw_line)
        if scalar:
            key, value = scalar.group(1), scalar.group(2).strip()
            if value:
                fm[key] = value.strip('"').strip("'")
                current_list = None
            else:
                # An empty value introduces a block list.
                fm[key] = []
                current_list = key
            continue
        # Anything indented and not an item (e.g. nested mapping) ends a list.
        if not raw_line.startswith((" ", "\t")):
            current_list = None
    return fm


def _statements_from_note(text: str) -> list[str]:
    """Extract a speaker's verbatim quotes from a note.

    Two shapes occur in practice and both must be handled:

    * frontmatter ``key_statements:`` entries written as ``- quote: "..."``
      (these are nested mappings, so the flat frontmatter parser yields
      ``'quote: "..."'`` -- the value has to be pulled out explicitly),
    * ``> quoted`` blockquote lines in the body's Key Statements section.

    The pre-existing parser read neither, which is why deterministic quote
    matching was impossible before.
    """
    out: list[str] = []

    fm_match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).splitlines():
            m = re.search(r"(?:^|[\s-])quote:\s*(.+)$", line)
            if m:
                value = m.group(1).strip().strip('"').strip("'")
                if value:
                    out.append(value)

    body = text[fm_match.end():] if fm_match else text
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            quote = stripped.lstrip(">").strip()
            if quote:
                out.append(quote)

    return list(dict.fromkeys(out))


def _as_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


class SpeakerRegistryStore:
    """Read the curated speaker registry and apply speaker mappings."""

    def __init__(self, speakers_dir: str, index_path: str):
        self._speakers_dir = Path(speakers_dir)
        self._index_path = Path(index_path)

    # -- loading ---------------------------------------------------------
    def load_index(self) -> dict:
        if not self._index_path.is_file():
            return {}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.exception("[speakers] invalid index JSON: %s", self._index_path)
            return {}

    def load_profiles(self) -> dict[str, SpeakerProfile]:
        """Join ``speaker_index.json`` with the ``*.md`` frontmatter.

        The index contributes ``segment_labels`` (the exact labels used in
        ``segment.speaker``); the markdown contributes ``aliases`` (for label and
        mention matching) and ``key_statements`` (for verbatim quote matching).
        """
        index = self.load_index()
        profiles: dict[str, SpeakerProfile] = {}

        for speaker_id, entry in (index.get("mapped_speakers") or {}).items():
            md_name = str(entry.get("md_file") or "")
            md_path = Path(md_name) if md_name else self._speakers_dir / f"{speaker_id}.md"
            if not md_path.is_file():
                md_path = self._speakers_dir / f"{speaker_id}.md"
            fm = parse_frontmatter(md_path.read_text(encoding="utf-8")) if md_path.is_file() else {}

            labels: list[str] = []
            for appearance in entry.get("appearances") or []:
                labels.extend(_as_tuple(appearance.get("segment_labels")))

            # Quotes come from the frontmatter's ``- quote: "..."`` entries and
            # from the body's ``> ...`` blockquotes; the flat parser cannot see
            # either, so they are extracted explicitly.
            statements = (
                _statements_from_note(md_path.read_text(encoding="utf-8"))
                if md_path.is_file()
                else []
            )

            profiles[speaker_id] = SpeakerProfile(
                speaker_id=speaker_id,
                display_name=str(entry.get("display_name") or fm.get("display_name") or ""),
                role=str(fm.get("role") or entry.get("role") or ""),
                organization=str(entry.get("organization") or fm.get("organization") or ""),
                identification_confidence=str(
                    entry.get("identification_confidence")
                    or fm.get("identification_confidence")
                    or ""
                ),
                aliases=_as_tuple(fm.get("aliases")),
                statements=tuple(dict.fromkeys(s for s in statements if s)),
                segment_labels=tuple(dict.fromkeys(labels)),
            )
        return profiles

    # -- per-transcript helpers -----------------------------------------
    def known_cast_for(
        self, transcript: Transcript, *, peer_transcript_ids: list[str] | None = None
    ) -> list[str]:
        """Speaker ids the registry already associates with this recording.

        The index keys appearances by ``transcript_id``, so a *new* run over a
        known recording cannot find its cast from its own id. ``peer_transcript_ids``
        is how the caller supplies the transcripts covering the same audio (see
        :meth:`audio_peers`); their cast becomes this run's cast.

        This matters most for exactly the case the feature exists for: a fresh
        diarization of an already-known recording.
        """
        index = self.load_index()
        wanted = {
            transcript.transcript_id,
            transcript.audio_id,
            transcript.narrative_id,
            transcript.source_file,
            *(peer_transcript_ids or []),
        }
        wanted.discard("")

        cast: list[str] = []
        for speaker_id, entry in (index.get("mapped_speakers") or {}).items():
            for appearance in entry.get("appearances") or []:
                tid = str(appearance.get("transcript_id") or "")
                if tid in wanted:
                    cast.append(speaker_id)
                    break
        return list(dict.fromkeys(cast))

    @staticmethod
    def audio_peers(transcripts: list[Transcript], transcript: Transcript) -> list[str]:
        """Ids of other transcripts covering the same audio as ``transcript``.

        Uses ``audio_id`` when present (the stable per-recording key), falling
        back to ``source_file`` so transcripts predating ``audio_id`` still match.
        """
        keys = {k for k in (transcript.audio_id, transcript.source_file) if k}
        if not keys:
            return []
        peers: list[str] = []
        for other in transcripts:
            if other.transcript_id == transcript.transcript_id:
                continue
            if keys & {k for k in (other.audio_id, other.source_file) if k}:
                peers.append(other.transcript_id)
        return peers

    @staticmethod
    def participant_labels(transcript: Transcript) -> dict[str, str]:
        """``raw label -> speaker_id`` already recorded on the participants."""
        out: dict[str, str] = {}
        for participant in transcript.participants or []:
            if not isinstance(participant, dict):
                continue
            speaker_id = str(participant.get("speaker_id") or "").strip()
            if not speaker_id:
                continue
            labels = participant.get("segment_labels") or []
            if isinstance(labels, str):
                labels = [labels]
            for label in labels:
                text = str(label).strip()
                if text:
                    out[text] = speaker_id
        return out

    @staticmethod
    def evidence_from(transcript: Transcript) -> list[SpeakerEvidence]:
        """Group a transcript's segments by raw diarization label."""
        grouped: dict[str, list[Segment]] = {}
        for segment in transcript.segments or []:
            grouped.setdefault(segment.speaker.label, []).append(segment)
        return [
            SpeakerEvidence(
                raw_label=label,
                segment_indices=tuple(s.index for s in segments),
                text=" ".join(s.text for s in segments if s.text),
            )
            for label, segments in grouped.items()
        ]

    # -- resolution ------------------------------------------------------
    def resolve(
        self,
        transcript: Transcript,
        profiles: dict[str, SpeakerProfile] | None = None,
        *,
        peer_transcript_ids: list[str] | None = None,
    ) -> SpeakerResolution:
        return resolve_speakers(
            transcript_id=transcript.transcript_id,
            evidence=self.evidence_from(transcript),
            profiles=profiles if profiles is not None else self.load_profiles(),
            known_cast=self.known_cast_for(transcript, peer_transcript_ids=peer_transcript_ids),
            participant_labels=self.participant_labels(transcript),
        )

    # -- applying --------------------------------------------------------
    def apply_map(
        self,
        transcript: Transcript,
        mapping: dict[str, str],
        *,
        reason: str = "speaker mapping",
    ) -> tuple[Transcript, dict]:
        """Persist ``{raw_label: speaker_id}`` onto a transcript.

        Returns the updated transcript and a report. Does not save; the caller
        owns persistence so the same code path serves preview and apply.
        """
        profiles = self.load_profiles()
        mapping = {
            label: speaker_id
            for label, speaker_id in (mapping or {}).items()
            if label and speaker_id
        }
        unknown = sorted({s for s in mapping.values() if s not in profiles})

        applied: dict[str, str] = {}
        segments: list[Segment] = []
        for segment in transcript.segments or []:
            speaker_id = mapping.get(segment.speaker.label)
            if not speaker_id or segment.speaker_id == speaker_id:
                segments.append(segment)
                continue
            applied[segment.speaker.label] = speaker_id
            segments.append(replace(segment, speaker_id=speaker_id))

        updated = replace(transcript, segments=segments)

        # Bridge: register each raw label under the participant that now owns it,
        # so generate_speaker_index_v3.py and the registry UI see the mapping
        # without any change to them.
        participants = [dict(p) if isinstance(p, dict) else p for p in (updated.participants or [])]
        for label, speaker_id in applied.items():
            for participant in participants:
                if not isinstance(participant, dict):
                    continue
                if str(participant.get("speaker_id") or "") != speaker_id:
                    continue
                labels = participant.get("segment_labels") or []
                if isinstance(labels, str):
                    labels = [labels]
                if label not in labels:
                    participant["segment_labels"] = [*labels, label]
                break
        if participants:
            updated = replace(updated, participants=participants)

        if applied:
            entry = {
                "segment": ", ".join(sorted(applied)),
                "original": ", ".join(sorted(applied)),
                "corrected": ", ".join(f"{k}->{v}" for k, v in sorted(applied.items())),
                "reason": reason,
                "type": "speaker_mapping",
            }
            updated = replace(
                updated,
                corrections_applied=[*(updated.corrections_applied or []), entry],
            )

        report = {
            "transcript_id": transcript.transcript_id,
            "applied": applied,
            "applied_count": len(applied),
            "segments_updated": sum(1 for s in segments if s.speaker_id),
            "unknown_speaker_ids": unknown,
            "requested": mapping,
        }
        return updated, report

    # -- consumable artifact --------------------------------------------
    def build_segment_map(self, transcripts: list[Transcript]) -> dict:
        """Build the machine-readable speaker+segment map for other consumers.

        Shape (stable, ``schema_version``-guarded)::

            {
              "schema_version": "1.0.0",
              "generated_utc": "...",
              "speakers": { "SPK-x": {display_name, role, organization,
                                      segment_count, segments: [...] } },
              "transcripts": { "<tid>": {speaker_map: {...},
                                         unresolved_labels: [...],
                                         segment_count: N } },
              "unresolved_segment_labels": {...}
            }
        """
        profiles = self.load_profiles()
        speakers: dict[str, dict] = {}
        transcripts_out: dict[str, dict] = {}
        unresolved: dict[str, int] = {}

        for transcript in transcripts:
            per_transcript: dict[str, str] = {}
            segment_count = 0
            for segment in transcript.segments or []:
                segment_count += 1
                speaker_id = (segment.speaker_id or "").strip()
                if not speaker_id:
                    # Fall back to the participants' recorded labels.
                    speaker_id = self.participant_labels(transcript).get(
                        segment.speaker.label, ""
                    )
                if not speaker_id:
                    unresolved[segment.speaker.label] = unresolved.get(segment.speaker.label, 0) + 1
                    continue
                profile = profiles.get(speaker_id)
                bucket = speakers.setdefault(
                    speaker_id,
                    {
                        "display_name": (profile.display_name if profile else "") or speaker_id,
                        "role": profile.role if profile else "",
                        "organization": profile.organization if profile else "",
                        "segment_count": 0,
                        "segments": [],
                    },
                )
                bucket["segment_count"] += 1
                bucket["segments"].append(
                    {
                        "transcript_id": transcript.transcript_id,
                        "segment_index": segment.index,
                        "speaker_label": segment.speaker.label,
                        "start": segment.start,
                        "end": segment.end,
                        "segment_datetime": segment.segment_datetime,
                    }
                )
                per_transcript[segment.speaker.label] = speaker_id

            transcripts_out[transcript.transcript_id] = {
                "speaker_map": per_transcript,
                "unresolved_labels": sorted(
                    {s.speaker.label for s in (transcript.segments or []) if s.speaker.label not in per_transcript}
                ),
                "segment_count": segment_count,
                "audio_id": transcript.audio_id,
                "narrative_id": transcript.narrative_id,
                "case_id": transcript.case_id,
            }

        for bucket in speakers.values():
            bucket["segments"].sort(key=lambda s: (s["transcript_id"], s["segment_index"]))

        return {
            "schema_version": _SCHEMA_VERSION,
            "generated_utc": _dt.datetime.now(_dt.UTC).isoformat(),
            "source": "data/transcripts/",
            "speaker_count": len(speakers),
            "transcript_count": len(transcripts_out),
            "speakers": dict(sorted(speakers.items())),
            "transcripts": dict(sorted(transcripts_out.items())),
            "unresolved_segment_labels": dict(
                sorted(unresolved.items(), key=lambda kv: -kv[1])
            ),
        }
