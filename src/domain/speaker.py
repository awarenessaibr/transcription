"""Speaker-profile and speaker-resolution domain types.

These are pure value objects: no I/O, no framework, no infrastructure. They are
the vocabulary shared by the resolver (application), the registry store
(infrastructure) and the speakers API (presentation).

Background
----------
Diarization emits opaque labels (``SPEAKER_00``, ``SPEAKER_01``). The speaker
registry holds curated identities (``SPK-...``) with display names, aliases and
verbatim key statements. Bridging the two is what this module describes:

* :class:`SpeakerProfile` — what the registry knows about one person
* :class:`SpeakerEvidence` — one raw label's observed segments
* :class:`SpeakerProposal` — a proposed ``raw label -> speaker`` mapping, with
  the signals that justify it and a confidence
* :class:`SpeakerResolution` — the whole proposal set for one transcript,
  including what could not be resolved
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Confidence values are deliberately coarse and named, not free-form floats:
# they are shown to a human who is deciding whether to accept a mapping, and a
# reviewer needs to know *why* something was proposed, not just how strongly.
CONF_AUTHORITATIVE = 1.0   # the transcript already recorded this mapping
CONF_STATEMENT = 0.85      # a verbatim known quote appears in this label's text
CONF_SINGLE_CAST = 0.9     # the recording is known to contain exactly one speaker
CONF_LABEL_ALIAS = 0.7     # the raw label itself matches a known alias
CONF_PRESENCE = 0.3        # the text *mentions* this person (presence, not identity)

#: Signals strong enough to be offered as a determination rather than a hint.
DETERMINING_SIGNALS = (
    "participant_segment_label",
    "single_known_speaker",
    "known_statement",
    "label_matches_alias",
)

#: Signals that only establish presence or narrow the field.
ADVISORY_SIGNALS = ("mentioned_by_other_speaker", "known_cast_candidate")


@dataclass(frozen=True)
class SpeakerProfile:
    """One curated identity from the speaker registry."""

    speaker_id: str
    display_name: str = ""
    role: str = ""
    organization: str = ""
    identification_confidence: str = ""
    aliases: tuple[str, ...] = ()
    #: Verbatim quotes known to be this speaker's words.
    statements: tuple[str, ...] = ()
    #: Raw segment labels this speaker is already known to appear as.
    segment_labels: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        """Display name plus aliases, for text matching."""
        out = [self.display_name, *self.aliases]
        return tuple(n for n in dict.fromkeys(n.strip() for n in out) if n)

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "display_name": self.display_name,
            "role": self.role,
            "organization": self.organization,
            "identification_confidence": self.identification_confidence,
            "aliases": list(self.aliases),
            "statement_count": len(self.statements),
            "segment_labels": list(self.segment_labels),
        }


@dataclass(frozen=True)
class SpeakerEvidence:
    """One raw diarization label and the segments observed under it."""

    raw_label: str
    segment_indices: tuple[int, ...] = ()
    text: str = ""

    @property
    def segment_count(self) -> int:
        return len(self.segment_indices)


@dataclass(frozen=True)
class SpeakerProposal:
    """A proposed mapping of one raw label onto one registry identity."""

    raw_label: str
    speaker_id: str
    display_name: str
    confidence: float
    signals: tuple[str, ...]
    segment_count: int = 0
    #: Other speakers whose names appear in this label's text (presence only).
    mentioned: tuple[str, ...] = ()
    #: Speaker ids this label could still be, narrowed by the recording's known
    #: cast. Populated even when the identity is undetermined, because choosing
    #: from a handful of known participants is the whole point of the registry.
    candidates: tuple[str, ...] = ()

    @property
    def determining(self) -> bool:
        return any(s in DETERMINING_SIGNALS for s in self.signals)

    def to_dict(self) -> dict:
        return {
            "raw_label": self.raw_label,
            "speaker_id": self.speaker_id,
            "display_name": self.display_name,
            "confidence": round(self.confidence, 3),
            "signals": list(self.signals),
            "determining": self.determining,
            "segment_count": self.segment_count,
            "mentioned": list(self.mentioned),
            "candidates": list(self.candidates),
        }


@dataclass(frozen=True)
class SpeakerResolution:
    """The full proposal set for one transcript."""

    transcript_id: str
    proposals: tuple[SpeakerProposal, ...] = ()
    unresolved_labels: tuple[str, ...] = ()
    known_cast: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict:
        return {
            "transcript_id": self.transcript_id,
            "known_cast": list(self.known_cast),
            "proposals": [p.to_dict() for p in self.proposals],
            "unresolved_labels": list(self.unresolved_labels),
            "notes": list(self.notes),
        }
