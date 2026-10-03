"""Resolve opaque diarization labels onto curated speaker identities.

Problem
-------
Diarization emits ``SPEAKER_00``, ``SPEAKER_01``, …. The speaker registry holds
curated identities (``SPK-...``) with display names, aliases and verbatim key
statements. Nothing bridged the two: a fresh run's labels stayed opaque, and the
existing 29 transcripts encode the mapping only implicitly, by hand, in
``participants[].segment_labels``.

This module proposes the mapping. It is **pure**: it takes evidence and profiles
and returns proposals. It performs no I/O, calls no model, and — critically —
**never writes anything**. Every proposal carries the signals that justify it so
a human can accept or reject it, which is the only defensible design for
attribution in an evidentiary record.

Signals, strongest first
------------------------
1. ``participant_segment_label`` (authoritative) — the transcript already
   records this raw label under a participant, i.e. a human already decided.
2. ``single_known_speaker`` — the recording is known to contain exactly one
   speaker, so every label must be that person.
3. ``known_statement`` — a verbatim quote known to belong to a speaker appears
   in the text attributed to this label. Deterministic and auditable.
4. ``label_matches_alias`` — the raw label itself is one of the speaker's names
   (e.g. a curated label such as ``antonella``).
5. ``mentioned_by_other_speaker`` (advisory only) — this label's text names
   another speaker. Establishes *presence*, not identity, so it never determines
   a mapping on its own.
"""
from __future__ import annotations

import re
import unicodedata

from src.domain.speaker import (
    CONF_LABEL_ALIAS,
    CONF_PRESENCE,
    CONF_SINGLE_CAST,
    CONF_STATEMENT,
    DETERMINING_SIGNALS,
    SpeakerEvidence,
    SpeakerProfile,
    SpeakerProposal,
    SpeakerResolution,
)

#: Short or generic names produce false positives when matched as substrings.
#: Matched names must be at least this many characters of folded text.
_MIN_NAME_LEN = 4

#: Known quotes shorter than this are too generic to identify anyone reliably.
_MIN_STATEMENT_LEN = 12


def fold(text: str) -> str:
    """Accent-fold, lowercase and collapse whitespace, for robust matching."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped).strip().lower()


def _mentions(haystack_folded: str, needle: str) -> bool:
    """Word-boundary contains, so 'Ana' does not match 'Susana'."""
    folded = fold(needle)
    if len(folded) < _MIN_NAME_LEN:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(folded)}(?![a-z0-9])", haystack_folded) is not None


def _normalise_label(label: str) -> str:
    """Fold a raw label for comparison, dropping the SPEAKER_nn noise."""
    return fold(label).replace("_", " ").strip()


#: Diarization's own placeholder labels. They are LOCAL TO ONE RECORDING:
#: ``SPEAKER_00`` in one file has no relationship to ``SPEAKER_00`` in another.
#: Matching them against a registry entry would silently attribute one
#: recording's speaker to a different recording's person -- observed in practice
#: when a stale profile carried ``SPEAKER_00`` in its segment_labels.
_GENERIC_LABEL_RE = re.compile(r"^speaker[\s_-]?\d+$")


def is_generic_label(label: str) -> bool:
    """True for diarization placeholders, which must not be matched globally."""
    return _GENERIC_LABEL_RE.match(_normalise_label(label)) is not None


def resolve_speakers(
    *,
    transcript_id: str,
    evidence: list[SpeakerEvidence],
    profiles: dict[str, SpeakerProfile],
    known_cast: list[str] | None = None,
    participant_labels: dict[str, str] | None = None,
) -> SpeakerResolution:
    """Propose a ``raw_label -> speaker_id`` mapping for one transcript.

    Args:
        transcript_id: for reporting.
        evidence: one entry per distinct raw diarization label.
        profiles: ``speaker_id -> SpeakerProfile`` from the registry.
        known_cast: speaker ids already known to appear in this recording.
        participant_labels: ``raw_label -> speaker_id`` already recorded on the
            transcript's participants. Authoritative when present.
    """
    known_cast = [s for s in (known_cast or []) if s in profiles]
    participant_labels = {
        k: v for k, v in (participant_labels or {}).items() if v in profiles
    }
    profiles_by_name: list[tuple[SpeakerProfile, str]] = [
        (p, name)
        for p in profiles.values()
        for name in p.names
        if len(fold(name)) >= _MIN_NAME_LEN
    ]

    proposals: list[SpeakerProposal] = []
    unresolved: list[str] = []

    for item in evidence:
        label_folded = _normalise_label(item.raw_label)
        text_folded = fold(item.text)
        signals: dict[str, float] = {}
        chosen: SpeakerProfile | None = None
        mentioned: list[str] = []

        # 1) Authoritative: already recorded on this transcript.
        preset = participant_labels.get(item.raw_label) or participant_labels.get(
            item.raw_label.strip()
        )
        if preset:
            chosen = profiles[preset]
            signals["participant_segment_label"] = 1.0

        # 2) The recording is known to contain exactly one speaker.
        if chosen is None and len(known_cast) == 1:
            chosen = profiles[known_cast[0]]
            signals["single_known_speaker"] = CONF_SINGLE_CAST

        # 3) A verbatim known quote appears under this label.
        if chosen is None and text_folded:
            for profile in profiles.values():
                hit = any(
                    len(fold(q)) >= _MIN_STATEMENT_LEN and fold(q) in text_folded
                    for q in profile.statements
                )
                if hit:
                    chosen = profile
                    signals["known_statement"] = CONF_STATEMENT
                    break

        # 4) The raw label itself is one of the speaker's names or known labels.
        #    Never applied to generic labels: they are recording-local, so a
        #    registry entry that happens to carry "SPEAKER_00" says nothing about
        #    *this* SPEAKER_00.
        if chosen is None and label_folded and not is_generic_label(item.raw_label):
            for profile in profiles.values():
                candidates = {
                    _normalise_label(n) for n in profile.names
                } | {_normalise_label(lbl) for lbl in profile.segment_labels}
                candidates.discard("")
                if label_folded in candidates:
                    chosen = profile
                    signals["label_matches_alias"] = CONF_LABEL_ALIAS
                    break

        # 5) Advisory: presence of other speakers in this label's text.
        if text_folded:
            for profile, name in profiles_by_name:
                if chosen is not None and profile.speaker_id == chosen.speaker_id:
                    continue
                if _mentions(text_folded, name):
                    mentioned.append(profile.display_name or profile.speaker_id)

        if chosen is None:
            unresolved.append(item.raw_label)
            # The identity is undetermined, but the recording's cast still
            # narrows the field. That is what turns "SPEAKER_03 is unknown" into
            # "SPEAKER_03 is one of these 7 people", which a human can settle.
            narrowed = tuple(s for s in known_cast if s in profiles)
            if narrowed or mentioned:
                signals_out = ()
                confidence = 0.0
                if mentioned:
                    signals_out = ("mentioned_by_other_speaker",)
                    confidence = CONF_PRESENCE
                elif narrowed:
                    signals_out = ("known_cast_candidate",)
                proposals.append(
                    SpeakerProposal(
                        raw_label=item.raw_label,
                        speaker_id="",
                        display_name="",
                        confidence=confidence,
                        signals=signals_out,
                        segment_count=item.segment_count,
                        mentioned=tuple(dict.fromkeys(mentioned)),
                        candidates=narrowed,
                    )
                )
            continue

        confidence = max(signals.values()) if signals else 0.0
        proposals.append(
            SpeakerProposal(
                raw_label=item.raw_label,
                speaker_id=chosen.speaker_id,
                display_name=chosen.display_name or chosen.speaker_id,
                confidence=confidence,
                signals=tuple(signals),
                segment_count=item.segment_count,
                mentioned=tuple(dict.fromkeys(mentioned)),
                # Alternatives, so a reviewer can correct the proposal in place.
                candidates=tuple(
                    s for s in known_cast if s != chosen.speaker_id and s in profiles
                ),
            )
        )

    notes: list[str] = []
    if not profiles:
        notes.append("speaker registry is empty: nothing to resolve against")
    if unresolved:
        notes.append(
            f"{len(unresolved)} label(s) could not be resolved from the registry: "
            "they need a human decision or a voiceprint match"
        )
    if any(p.speaker_id == "" and p.mentioned for p in proposals):
        notes.append("entries with no speaker_id are presence hints only, not identities")
    generic_left = [lbl for lbl in unresolved if is_generic_label(lbl)]
    if generic_left:
        notes.append(
            f"{len(generic_left)} generic diarization label(s) could not be resolved: "
            "SPEAKER_nn is local to one recording, so identity needs a known cast, "
            "a verbatim quote match, or a human/voiceprint decision"
        )

    return SpeakerResolution(
        transcript_id=transcript_id,
        proposals=tuple(proposals),
        unresolved_labels=tuple(unresolved),
        known_cast=tuple(known_cast),
        notes=tuple(notes),
    )


def proposals_to_map(resolution: SpeakerResolution, *, min_confidence: float = 0.0) -> dict[str, str]:
    """Collapse a resolution into ``{raw_label: speaker_id}``.

    Only determining signals are eligible, and only at or above
    ``min_confidence``; advisory presence hints are never included.
    """
    out: dict[str, str] = {}
    for p in resolution.proposals:
        if not p.speaker_id or not p.determining:
            continue
        if p.confidence < min_confidence:
            continue
        out[p.raw_label] = p.speaker_id
    return out


def determining_signals() -> tuple[str, ...]:
    """Expose the determining-signal vocabulary (used by tests and the API)."""
    return DETERMINING_SIGNALS
