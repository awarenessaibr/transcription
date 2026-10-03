"""Tests for the speaker resolver.

The resolver proposes ``SPEAKER_nn -> SPK-...`` mappings and must never invent
one: every proposal carries the signal that justifies it. These tests pin both
the signal semantics and the refusal behaviour, because the output is shown to a
human deciding attribution in an evidentiary record.

See docs/SPEAKER_RESOLUTION.md.
"""
from __future__ import annotations

from src.application.services.speaker_resolver import (
    fold,
    proposals_to_map,
    resolve_speakers,
)
from src.domain.speaker import (
    CONF_LABEL_ALIAS,
    CONF_SINGLE_CAST,
    CONF_STATEMENT,
    SpeakerEvidence,
    SpeakerProfile,
)


def _profiles() -> dict[str, SpeakerProfile]:
    return {
        "SPK-passenger-leandro": SpeakerProfile(
            speaker_id="SPK-passenger-leandro",
            display_name="Leandro Disconzi",
            role="Passenger",
            organization="self",
            identification_confidence="confirmed",
            aliases=("Leandro",),
            statements=("quiero entender el por que",),
            segment_labels=("passenger",),
        ),
        "SPK-antonela-latam-agent": SpeakerProfile(
            speaker_id="SPK-antonela-latam-agent",
            display_name="Antonela",
            role="Agent / Supervisor",
            organization="LATAM Airlines",
            identification_confidence="partial",
            aliases=("Anto", "Antonella"),
            statements=("esta es la carta que usted pidio",),
            segment_labels=("airline_supervisor",),
        ),
        "SPK-dgac-edgardo-ortiz": SpeakerProfile(
            speaker_id="SPK-dgac-edgardo-ortiz",
            display_name="Edgardo Ortiz",
            identification_confidence="confirmed",
        ),
    }


def _ev(label: str, text: str = "", indices=(0,)) -> SpeakerEvidence:
    return SpeakerEvidence(raw_label=label, segment_indices=tuple(indices), text=text)


# --------------------------------------------------------------------------
# fold()
# --------------------------------------------------------------------------
def test_fold_is_accent_insensitive_and_case_insensitive() -> None:
    assert fold("Antónela  RAMÍREZ") == "antonela ramirez"
    assert fold("") == ""
    assert fold(None) == ""  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Signal 1: authoritative participant mapping
# --------------------------------------------------------------------------
def test_participant_mapping_is_authoritative() -> None:
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("SPEAKER_00", "cualquier texto")],
        profiles=_profiles(),
        participant_labels={"SPEAKER_00": "SPK-passenger-leandro"},
    )
    p = res.proposals[0]
    assert p.speaker_id == "SPK-passenger-leandro"
    assert p.confidence == 1.0
    assert "participant_segment_label" in p.signals
    assert p.determining
    assert res.unresolved_labels == ()


def test_participant_mapping_beats_a_statement_match() -> None:
    """An explicit human decision outranks an inferred one."""
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("SPEAKER_00", "esta es la carta que usted pidio")],
        profiles=_profiles(),
        participant_labels={"SPEAKER_00": "SPK-passenger-leandro"},
    )
    assert res.proposals[0].speaker_id == "SPK-passenger-leandro"
    assert res.proposals[0].signals == ("participant_segment_label",)


# --------------------------------------------------------------------------
# Signal 2: single known speaker
# --------------------------------------------------------------------------
def test_single_known_speaker_maps_every_label() -> None:
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("SPEAKER_00"), _ev("SPEAKER_01", indices=(1,))],
        profiles=_profiles(),
        known_cast=["SPK-dgac-edgardo-ortiz"],
    )
    assert {p.speaker_id for p in res.proposals} == {"SPK-dgac-edgardo-ortiz"}
    assert all("single_known_speaker" in p.signals for p in res.proposals)
    assert res.proposals[0].confidence == CONF_SINGLE_CAST


def test_two_known_speakers_does_not_trigger_single_cast() -> None:
    """With more than one candidate the resolver refuses to pick one.

    It still narrows the field, which is the registry's main contribution: the
    label becomes "one of these two" rather than unknown.
    """
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("SPEAKER_00")],
        profiles=_profiles(),
        known_cast=["SPK-dgac-edgardo-ortiz", "SPK-antonela-latam-agent"],
    )
    assert res.unresolved_labels == ("SPEAKER_00",)
    p = res.proposals[0]
    assert p.speaker_id == "", "must not guess between two candidates"
    assert not p.determining
    assert set(p.candidates) == {"SPK-dgac-edgardo-ortiz", "SPK-antonela-latam-agent"}
    assert proposals_to_map(res) == {}


def test_candidates_narrow_a_generic_label_to_the_recordings_cast() -> None:
    """The point of the registry: 45 possible people -> the 3 actually present."""
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("SPEAKER_05", "texto irrelevante")],
        profiles=_profiles(),
        known_cast=[
            "SPK-dgac-edgardo-ortiz",
            "SPK-antonela-latam-agent",
            "SPK-passenger-leandro",
        ],
    )
    p = res.proposals[0]
    assert p.speaker_id == ""
    assert len(p.candidates) == 3
    assert "known_cast_candidate" in p.signals
    assert any("generic diarization label" in n for n in res.notes)


def test_a_determined_proposal_lists_the_alternatives() -> None:
    """A reviewer must be able to correct a wrong proposal in place."""
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("antonella")],
        profiles=_profiles(),
        known_cast=["SPK-antonela-latam-agent", "SPK-dgac-edgardo-ortiz"],
    )
    p = res.proposals[0]
    assert p.speaker_id == "SPK-antonela-latam-agent"
    assert p.candidates == ("SPK-dgac-edgardo-ortiz",)


# --------------------------------------------------------------------------
# Signal 3: verbatim known statement
# --------------------------------------------------------------------------
def test_known_statement_identifies_the_label() -> None:
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("SPEAKER_01", "Mira, esta es la carta que usted pidió, ¿ya?")],
        profiles=_profiles(),
    )
    p = res.proposals[0]
    assert p.speaker_id == "SPK-antonela-latam-agent"
    assert "known_statement" in p.signals
    assert p.confidence == CONF_STATEMENT


def test_short_statements_are_not_used() -> None:
    """A short quote is too generic to attribute a speaker."""
    profiles = {
        "SPK-x": SpeakerProfile(speaker_id="SPK-x", display_name="X", statements=("si",))
    }
    res = resolve_speakers(
        transcript_id="t", evidence=[_ev("SPEAKER_00", "si, claro")], profiles=profiles
    )
    assert res.proposals == ()
    assert res.unresolved_labels == ("SPEAKER_00",)


# --------------------------------------------------------------------------
# Signal 4: the raw label is a known alias / known label
# --------------------------------------------------------------------------
def test_label_matching_an_alias_resolves() -> None:
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("antonella")],
        profiles=_profiles(),
    )
    assert res.proposals[0].speaker_id == "SPK-antonela-latam-agent"
    assert "label_matches_alias" in res.proposals[0].signals
    assert res.proposals[0].confidence == CONF_LABEL_ALIAS


def test_label_matching_a_known_segment_label_resolves() -> None:
    res = resolve_speakers(
        transcript_id="t", evidence=[_ev("passenger")], profiles=_profiles()
    )
    assert res.proposals[0].speaker_id == "SPK-passenger-leandro"


def test_unrelated_opaque_label_stays_unresolved() -> None:
    res = resolve_speakers(
        transcript_id="t", evidence=[_ev("SPEAKER_07")], profiles=_profiles()
    )
    assert res.proposals == ()
    assert res.unresolved_labels == ("SPEAKER_07",)


# --------------------------------------------------------------------------
# Signal 5: presence is advisory only
# --------------------------------------------------------------------------
def test_mention_is_presence_only_never_an_identity() -> None:
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("SPEAKER_00", "Antonela me dijo que no podia embarcar")],
        profiles=_profiles(),
    )
    assert res.proposals, "presence should still be reported"
    p = res.proposals[0]
    assert p.speaker_id == "", "a mention must not determine identity"
    assert not p.determining
    assert "Antonela" in p.mentioned
    assert "SPEAKER_00" in res.unresolved_labels
    # and it must never leak into an applied mapping
    assert proposals_to_map(res) == {}


def test_presence_does_not_override_a_determination() -> None:
    """The speaker themselves is not listed as merely 'mentioned'."""
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("antonella", "Antonela: hola, soy Antonela")],
        profiles=_profiles(),
    )
    p = res.proposals[0]
    assert p.speaker_id == "SPK-antonela-latam-agent"
    assert "Antonela" not in p.mentioned


# --------------------------------------------------------------------------
# Matching safety
# --------------------------------------------------------------------------
def test_short_names_do_not_match_as_substrings() -> None:
    """'Ana' must not resolve inside 'Susana'."""
    profiles = {"SPK-ana": SpeakerProfile(speaker_id="SPK-ana", display_name="Ana")}
    res = resolve_speakers(
        transcript_id="t", evidence=[_ev("SPEAKER_00", "Susana llego tarde")], profiles=profiles
    )
    assert proposals_to_map(res) == {}
    assert res.proposals == ()


def test_accent_folding_matches_names() -> None:
    profiles = {"SPK-a": SpeakerProfile(speaker_id="SPK-a", display_name="Antónela")}
    res = resolve_speakers(
        transcript_id="t", evidence=[_ev("SPEAKER_00", "antonela respondio")], profiles=profiles
    )
    assert res.proposals[0].mentioned == ("Antónela",)


# --------------------------------------------------------------------------
# proposals_to_map
# --------------------------------------------------------------------------
def test_proposals_to_map_excludes_advisory_and_respects_threshold() -> None:
    res = resolve_speakers(
        transcript_id="t",
        evidence=[
            _ev("antonella"),                                        # 0.7
            _ev("SPEAKER_01", "esta es la carta que usted pidio"),   # 0.85
            _ev("SPEAKER_02", "Edgardo Ortiz dijo que no"),          # presence only
        ],
        profiles=_profiles(),
    )
    full = proposals_to_map(res)
    assert full == {
        "antonella": "SPK-antonela-latam-agent",
        "SPEAKER_01": "SPK-antonela-latam-agent",
    }
    strict = proposals_to_map(res, min_confidence=0.8)
    assert strict == {"SPEAKER_01": "SPK-antonela-latam-agent"}


def test_empty_registry_reports_a_note_and_resolves_nothing() -> None:
    res = resolve_speakers(
        transcript_id="t", evidence=[_ev("SPEAKER_00", "hola")], profiles={}
    )
    assert res.proposals == ()
    assert res.unresolved_labels == ("SPEAKER_00",)
    assert any("empty" in n for n in res.notes)


def test_resolution_is_serialisable() -> None:
    """The API returns this shape; keep it stable."""
    res = resolve_speakers(
        transcript_id="t",
        evidence=[_ev("antonella", indices=(1, 2))],
        profiles=_profiles(),
        known_cast=["SPK-antonela-latam-agent"],
    )
    payload = res.to_dict()
    assert payload["transcript_id"] == "t"
    assert payload["known_cast"] == ["SPK-antonela-latam-agent"]
    proposal = payload["proposals"][0]
    assert proposal["raw_label"] == "antonella"
    assert proposal["speaker_id"] == "SPK-antonela-latam-agent"
    assert proposal["segment_count"] == 2
    assert isinstance(proposal["confidence"], float)
    assert proposal["determining"] is True
