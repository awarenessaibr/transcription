"""Transcript field mapping and validation.

Single source of truth for every field a transcript JSON carries: its type,
whether it is required, its default, and how to validate/coerce it. Consumers
can use ``TRANSCRIPT_FIELDS`` to enumerate the schema and ``validate_transcript``
to check an incoming dict (or a loaded transcript) against it.

This module is intentionally dependency-free (domain layer): it must not import
the store, the router, or any infrastructure adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Type tags
# ---------------------------------------------------------------------------
STR = "str"
INT = "int"
FLOAT = "float"
BOOL = "bool"
LIST = "list"
DICT = "dict"


@dataclass(frozen=True)
class FieldSpec:
    """Declarative description of a single transcript field."""

    key: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None
    nullable: bool = False
    # For ``list``: expected element type (one of the tags above).
    item_type: str | None = None
    # Optional closed set of accepted values.
    allowed_values: tuple | None = None


# ---------------------------------------------------------------------------
# The field map
# ---------------------------------------------------------------------------
TRANSCRIPT_FIELDS: dict[str, FieldSpec] = {
    # -- identity -----------------------------------------------------------
    "transcript_id": FieldSpec(
        "transcript_id", STR,
        description="Unique identifier; also the JSON filename stem.",
        required=True,
    ),
    "original_transcript_id": FieldSpec(
        "original_transcript_id", STR,
        description="ID of the transcript this one was derived from (patch/refine).",
        nullable=True,
    ),
    "source_file": FieldSpec(
        "source_file", STR,
        description="Filename of the source audio recording (e.g. 'Aeropuerto ... 29.m4a').",
    ),
    "source_path": FieldSpec(
        "source_path", STR,
        description="Workspace-relative path to the source audio recording.",
    ),
    "audio_id": FieldSpec(
        "audio_id", STR,
        description=(
            "Short audio identifier used for source-audio mapping (e.g. "
            "'aeropuerto_STG_29'). The stage component is upper case."
        ),
    ),

    # -- provenance / stages ------------------------------------------------
    "chronological_order": FieldSpec(
        "chronological_order", INT,
        description="Ordinal position of this recording in the case timeline.",
        nullable=True,
    ),
    "prior_stage": FieldSpec(
        "prior_stage", STR,
        description="Stage ID that precedes this one (e.g. 'I-002_16_NAR-20_STG_28').",
    ),
    "next_stage": FieldSpec(
        "next_stage", STR,
        description="Stage ID that follows this one (e.g. 'I-002_18_NAR_LATAM_STG_2').",
    ),

    # -- descriptive metadata -----------------------------------------------
    "title": FieldSpec("title", STR, description="Human-readable transcript title."),
    "subtitle": FieldSpec("subtitle", STR, description="Short descriptive subtitle."),
    "location": FieldSpec(
        "location", STR,
        description=(
            "Where the recording took place. Canonical form is the facility "
            "'Arturo Merino Benítez International Airport (SCL), Santiago, Chile', "
            "optionally followed by ' — <place>'."
        ),
    ),
    "case_id": FieldSpec("case_id", STR, description="Case identifier (e.g. 'I-002')."),
    "narrative_id": FieldSpec("narrative_id", STR, description="Narrative identifier (e.g. 'NAR-21_STG_29')."),
    "classification": FieldSpec(
        "classification", STR,
        description="Handling classification / privilege marking.",
    ),
    "recording_datetime": FieldSpec(
        "recording_datetime", STR,
        description="Recording timestamp as an ISO-8601 string (e.g. '2024-07-05T19:45:00').",
    ),
    "timestamp": FieldSpec(
        "timestamp", STR,
        description="Ingestion/processing timestamp as an ISO-8601 string.",
    ),
    "language": FieldSpec(
        "language", STR,
        description="Language code (ISO 639-1), defaults to 'es'.",
        default="es",
    ),
    "provider": FieldSpec(
        "provider", STR,
        description="Source provider or importer (e.g. 'csv_import').",
    ),

    # -- structured containers ----------------------------------------------
    "metadata": FieldSpec(
        "metadata", DICT,
        description="Free-form metadata key/value map.",
    ),
    "participants": FieldSpec(
        "participants", LIST,
        description="List of participant objects (see PARTICIPANT_FIELDS).",
        item_type=DICT,
    ),
    "violations_cited": FieldSpec(
        "violations_cited", LIST,
        description=(
            "Registry IDs of cited violations (e.g. 'CL-038', 'INT-003'). "
            "IDs resolve against the incident violation registry."
        ),
        item_type=STR,
    ),
    "tags": FieldSpec(
        "tags", LIST,
        description="List of tags applied to the transcript, each 'lower-kebab-case'.",
        item_type=STR,
    ),
    "forensic_clusters": FieldSpec(
        "forensic_clusters", DICT,
        description=(
            "Named forensic clusters; each value follows CLUSTER_FIELDS."
        ),
    ),
    "key_evidentiary_findings": FieldSpec(
        "key_evidentiary_findings", LIST,
        description="List of evidentiary findings (see FINDING_FIELDS).",
        item_type=DICT,
    ),
    "corrections_applied": FieldSpec(
        "corrections_applied", LIST,
        description="List of corrections applied during review (see CORRECTION_FIELDS).",
        item_type=DICT,
    ),
    "segments": FieldSpec(
        "segments", LIST,
        description="List of transcript segments (see SEGMENT_FIELDS).",
        required=True,
        item_type=DICT,
    ),
    "reviewed": FieldSpec(
        "reviewed", BOOL,
        description=(
            "Whether a human has reviewed this transcript as a whole. "
            "Distinct from the per-segment 'reviewed' flag in SEGMENT_FIELDS."
        ),
        default=False,
    ),
}

# Segment sub-schema.
SEGMENT_FIELDS: dict[str, FieldSpec] = {
    "index": FieldSpec("index", INT, description="Segment index.", required=True),
    "speaker": FieldSpec("speaker", STR, description="Speaker label.", required=True),
    "start": FieldSpec("start", FLOAT, description="Start time in seconds.", required=True),
    "end": FieldSpec("end", FLOAT, description="End time in seconds.", required=True),
    "duration": FieldSpec("duration", FLOAT, description="Computed duration (end - start)."),
    "text": FieldSpec("text", STR, description="Transcribed text.", default=""),
    "reviewed": FieldSpec("reviewed", BOOL, description="Whether the segment was reviewed.", default=False),
    "correction_note": FieldSpec(
        "correction_note", STR,
        description="Curator correction note for the segment.",
        default="",
    ),
    "backchannel_events": FieldSpec(
        "backchannel_events", STR,
        description="Curator backchannel-events note for the segment.",
        default="",
    ),
}

# Participant sub-schema.
PARTICIPANT_FIELDS: dict[str, FieldSpec] = {
    "canonical_name": FieldSpec("canonical_name", STR, description="Canonical person name."),
    "role": FieldSpec("role", STR, description="Role in the interaction (e.g. 'Passenger')."),
    "speaker_label": FieldSpec("speaker_label", STR, description="Display label used in segments."),
    "speaker_id": FieldSpec("speaker_id", STR, description="Stable speaker identifier (enriched)."),
}

# Controlled vocabularies.  Values outside these sets are reported as warnings
# so vocabulary drift is caught at ingest rather than silently accumulating.
STRENGTH_VALUES: tuple[str, ...] = ("High", "Medium", "Low")

# Evidentiary finding sub-schema.
FINDING_FIELDS: dict[str, FieldSpec] = {
    "id": FieldSpec("id", STR, description="Finding ID (e.g. 'S29-1')."),
    "finding": FieldSpec("finding", STR, description="Finding description."),
    "strength": FieldSpec(
        "strength", STR,
        description="Finding strength.",
        allowed_values=STRENGTH_VALUES,
    ),
    "segments": FieldSpec(
        "segments", LIST,
        description="Segment references supporting the finding (index or 'a-b' range).",
        item_type=STR,
    ),
    "cross_reference": FieldSpec(
        "cross_reference", STR,
        description="Free-text cross-reference to related findings or stages.",
    ),
}

# Forensic cluster sub-schema.  Every key is optional: thin clusters carry only
# ``summary`` and ``segments``, richer ones add the analytical keys.
CLUSTER_FIELDS: dict[str, FieldSpec] = {
    "summary": FieldSpec("summary", STR, description="Narrative summary of the cluster."),
    "reasoning": FieldSpec("reasoning", STR, description="Analytical reasoning behind the cluster."),
    "provisions_engaged": FieldSpec(
        "provisions_engaged", LIST,
        description="Legal provisions engaged by the cluster.",
        item_type=STR,
    ),
    "violation_linkage": FieldSpec(
        "violation_linkage", STR,
        description="How the cluster links to the cited violations.",
    ),
    "segments": FieldSpec(
        "segments", LIST,
        description="Segment references spanned by the cluster.",
        item_type=STR,
    ),
}

# Correction sub-schema.  ``type`` distinguishes a description of curator
# process (``"process_note"``) from an ``original`` -> ``corrected`` rewrite.
CORRECTION_FIELDS: dict[str, FieldSpec] = {
    "segment": FieldSpec("segment", STR, description="Segment the correction applies to.", default=""),
    "original": FieldSpec("original", STR, description="Text as originally transcribed.", default=""),
    "corrected": FieldSpec("corrected", STR, description="Text after correction.", default=""),
    "reason": FieldSpec("reason", STR, description="Why the correction was made.", default=""),
    "type": FieldSpec(
        "type", STR,
        description="Correction category; used when the entry describes process rather than a rewrite.",
    ),
}

# Container key -> sub-schema applied to each contained object.
_NESTED_SCHEMAS: dict[str, dict[str, FieldSpec]] = {
    "segments": SEGMENT_FIELDS,
    "key_evidentiary_findings": FINDING_FIELDS,
    "corrections_applied": CORRECTION_FIELDS,
    "forensic_clusters": CLUSTER_FIELDS,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@dataclass
class ValidationReport:
    """Result of validating a transcript dict."""

    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    normalized: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
        }


_COERCERS: dict[str, Callable[[Any], Any]] = {
    STR: lambda v: str(v),
    INT: lambda v: int(v),
    FLOAT: lambda v: float(v),
    BOOL: lambda v: bool(v),
    LIST: lambda v: list(v),
    DICT: lambda v: dict(v),
}


def _matches_type(value: Any, type_tag: str) -> bool:
    if type_tag == STR:
        return isinstance(value, str)
    if type_tag == INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if type_tag == FLOAT:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_tag == BOOL:
        return isinstance(value, bool)
    if type_tag == LIST:
        return isinstance(value, list)
    if type_tag == DICT:
        return isinstance(value, dict)
    return True


def _coerce(value: Any, spec: FieldSpec) -> Any:
    """Best-effort coercion of ``value`` to ``spec.type``, or None on failure."""
    if value is None:
        return None
    if _matches_type(value, spec.type):
        return value
    try:
        coerced = _COERCERS[spec.type](value)
    except Exception:
        return None
    if spec.type == INT and isinstance(value, str):
        # Accept "17" and "17.0" but not "abc".
        try:
            return int(float(value))
        except Exception:
            return None
    return coerced


def _check_item_types(value: list, spec: FieldSpec, path: str, report: ValidationReport) -> None:
    if spec.item_type is None:
        return
    for i, item in enumerate(value):
        if not _matches_type(item, spec.item_type):
            report.warnings.append(
                f"{path}[{i}]: expected {spec.item_type}, got {type(item).__name__}"
            )


def validate_transcript(data: dict) -> ValidationReport:
    """Validate ``data`` (a transcript dict) against ``TRANSCRIPT_FIELDS``.

    Returns a :class:`ValidationReport` with hard errors (missing required
    field or value that cannot be coerced), soft warnings (coerced/empty
    optional fields), and a ``normalized`` dict of coerced values.
    """
    report = ValidationReport()
    if not isinstance(data, dict):
        report.ok = False
        report.errors.append("transcript data must be a JSON object")
        return report

    for key, spec in TRANSCRIPT_FIELDS.items():
        present = key in data
        value = data.get(key, spec.default)

        if not present and spec.required:
            report.ok = False
            report.errors.append(f"missing required field: {key}")
            continue

        if value is None:
            if spec.nullable:
                report.normalized[key] = None
                continue
            if spec.required:
                report.ok = False
                report.errors.append(f"required field is null: {key}")
                continue
            report.normalized[key] = spec.default
            continue

        coerced = _coerce(value, spec)
        if coerced is None and value is not None:
            report.ok = False
            report.errors.append(
                f"{key}: cannot coerce {value!r} to {spec.type}"
            )
            continue

        if not _matches_type(value, spec.type):
            report.warnings.append(
                f"{key}: coerced {type(value).__name__} -> {spec.type}"
            )

        if spec.allowed_values and coerced not in spec.allowed_values:
            report.warnings.append(
                f"{key}: {coerced!r} not in allowed values {spec.allowed_values}"
            )

        if isinstance(coerced, list):
            _check_item_types(coerced, spec, key, report)

        report.normalized[key] = coerced

    # Validate the nested object containers against their declared sub-schemas.
    for key, sub in _NESTED_SCHEMAS.items():
        value = report.normalized.get(key)
        if isinstance(value, list):
            for i, item in enumerate(value):
                _check_nested(item, sub, f"{key}[{i}]", report)
        elif isinstance(value, dict):
            for name, item in value.items():
                _check_nested(item, sub, f"{key}.{name}", report)

    return report


def _check_nested(
    value: Any,
    sub: dict[str, FieldSpec],
    path: str,
    report: ValidationReport,
) -> None:
    """Check one nested object against ``sub``, recording errors and warnings."""
    if not isinstance(value, dict):
        report.ok = False
        report.errors.append(f"{path}: expected object, got {type(value).__name__}")
        return

    for name, spec in sub.items():
        if name not in value:
            if spec.required:
                report.ok = False
                report.errors.append(f"{path}: missing required field {name}")
            continue

        item = value[name]
        if item is not None and not _matches_type(item, spec.type):
            report.warnings.append(
                f"{path}.{name}: expected {spec.type}, got {type(item).__name__}"
            )
            continue
        if spec.allowed_values and item not in spec.allowed_values:
            report.warnings.append(
                f"{path}.{name}: {item!r} not in allowed values {spec.allowed_values}"
            )
