#!/usr/bin/env python3
"""
generate_speaker_patch.py — Generate a machine-readable JSON patch file from the
speaker mapping analysis in .dev/speaker-map-updates.md.

Output: data/speaker_patch.json
Schema per entry:
  {
    "transcript_id": str,
    "segment_index": int,
    "old_speaker": str,        # current generic label in the file
    "suggested_speaker_id": str,  # target SPK-... key or "NEEDS_HUMAN_REVIEW"
    "confidence": "auto" | "review"  # "auto" = safe to apply; "review" = needs human
  }
"""

import json
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
transcripts_dir = repo_root / "data" / "transcripts"
output_file = repo_root / "data" / "speaker_patch.json"

# ---------------------------------------------------------------------------
# Canonicalisation of suggested ids
# ---------------------------------------------------------------------------
# The MAPPING_RULES below were authored against the *pre-consolidation* speaker
# vocabulary. ``fix_speaker_ids.py`` has since collapsed 46 raw ids into 35
# canonical ones, so a raw suggestion emitted verbatim would either miss the
# target profile or re-introduce the very fragmentation that was removed.
# Import the authoritative table rather than duplicating it.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fix_speaker_ids import CANONICAL  # noqa: E402

# Scoped ids that never appeared in any transcript, so CANONICAL has no entry
# for them. Each one is resolved explicitly:
#
#   SPK-dgac-official-2-angry-one-…  the `dgac_official 2` label (space) is a
#       typo of `dgac_official_2`, the segment label owned by
#       SPK-dgac-official-2 in I-002_12; "angry one" is a free-text descriptor.
#
#   SPK-dgac-of-…  the generic `dgac_official` label in I-002_12 is contested:
#       participant SPK-dgac-edgardo-ortiz already declares it, and no canonical
#       "unattributed DGAC official" bucket exists. Guessing here would silently
#       mis-attribute evidence, so the rule is sent for human review.
LEGACY_SCOPED = {
    "SPK-dgac-official-2-angry-one-nar-15-stg-22-dgac-office": "SPK-dgac-official-2",
    "SPK-dgac-of-nar-15-stg-22-dgac-office": "NEEDS_HUMAN_REVIEW",
}


def canonicalise(suggested_id: str, confidence: str) -> tuple[str, str]:
    """Return ``(suggested_id, confidence)`` with the id mapped to canonical form.

    >>> canonicalise("SPK-dgac-nar-06-stg-6-jetbridge-standoff", "auto")
    ('SPK-dgac', 'auto')
    >>> canonicalise("SPK-dgac-official-2-angry-one-nar-15-stg-22-dgac-office", "auto")
    ('SPK-dgac-official-2', 'auto')
    >>> canonicalise("SPK-dgac-of-nar-15-stg-22-dgac-office", "auto")
    ('NEEDS_HUMAN_REVIEW', 'review')
    >>> canonicalise("SPK-pdi-female", "auto")
    ('SPK-pdi-female', 'auto')
    """
    if suggested_id in LEGACY_SCOPED:
        suggested_id = LEGACY_SCOPED[suggested_id]
    else:
        suggested_id = CANONICAL.get(suggested_id, suggested_id)
    if suggested_id == "NEEDS_HUMAN_REVIEW":
        confidence = "review"
    return suggested_id, confidence

# ---------------------------------------------------------------------------
# Mapping table derived from .dev/speaker-map-updates.md (section 2 onwards)
# Format: (transcript_id, old_speaker_label) -> (suggested_speaker_id, confidence)
# For cases requiring human review, use "NEEDS_HUMAN_REVIEW"
# ---------------------------------------------------------------------------

TRANSCRIPT_ID_MAP = {
    # The actual transcript_id values found in data/transcripts/
    "I-002_02": "I-002_02_NAR-02_STG_2_boarding_gate",
    "I-002_03": "I-002_03_NAR-05_STG_5_aircraft_removal",
    "I-002_04": "I-002_04_NAR-06_STG_6_jetbridge_standoff",
    "I-002_05": "I-002_05_NAR-07_STG_7_post_removal_investigation",
    "I-002_06": "I-002_06_NAR-STG_8_pdi_identity_control",
    "I-002_08": "I-002_08_NAR-09_STG_15_luggage_recovery",
    "I-002_09": "I-002_09_NAR-10_STG_16_counter_confrontation",
    "I-002_10": "I-002_10_NAR-14_Terminal_Internacional_T2_counter",
    "I-002_10A": "I-002_10A_NAR-19_STG_19_counter_escalation",
    "I-002_11": "I-002_11_NAR-13_STG_20_barraza_counter",
    "I-002_12": "I-002_12_NAR-15_STG_22_DGAC_office",
    "I-002_13": "I-002_13_NAR-18_STG_26_self_narration",
    "I-002_14": "I-002_14_NAR-16_STG_23_DGAC_don_nicolas",
    "I-002_16": "I-002_16_NAR-20_STG_28",
    "I-002_17": "I-002_17_NAR-21_STG_29",
    "I-002_19": "I-002_19_NAR_LATAM_STG_3",
    "I-002_20": "I-002_20_NAR_LATAM_STG_4",
    "I-002_21": "I-002_21_NAR_CARABINEROS_1",
    "I-002_22": "I-002_22_NAR_CARABINEROS_2",
    "I-002_23": "I-002_23_NAR_CARABINEROS_3",
    "I-002_24": "I-002_24_NAR-19_STG_12",
}

# Each entry: (short_key, old_speaker_label, indices, suggested_speaker_id, confidence)
MAPPING_RULES = [
    # --- I-002_02 ---
    ("I-002_02", "airline_staff", [1], "SPK-latam-gate-staff-nar-02-stg-2-boarding-gate", "auto"),
    ("I-002_02", "airline_staff", [3,5,8,10,12,14,16,18,20,22,25,26,28,34,36,38,40,42,45,46,48,49,51], "SPK-latam-staff-acuser", "review"),
    ("I-002_02", "airline_staff", [53,55,57,59], "SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate", "auto"),
    ("I-002_02", "unresolved_speaker", [17], "SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate", "auto"),

    # --- I-002_03 ---
    ("I-002_03", "airline_cabin_crew", [1,5,8,10,11,13,15,17,19,21,23,25,27], "SPK-stewardess-accuser", "auto"),

    # --- I-002_04 ---
    ("I-002_04", "airline_cabin_crew", [0,2,4,6,8,10,15,20,22,23,24,26,28], "SPK-stewardess-accuser", "auto"),
    ("I-002_04", "airline_security_official", [33,35,37,39,41,48,50,52,54,55,57,60,64,67,70,123,125,131,133], "SPK-joaquin-barraza-latam-security", "auto"),
    ("I-002_04", "airline_pilot", [68,69,71,73], "SPK-pilot-ruiz", "auto"),
    ("I-002_04", "dgac_official", [75,76,78,79,80,83,84,86,88,90,92,93,95,99,101,103,105,107,109,116,120,135,137,140,142,149,150,151,154,156,159,164,165,176,177,180,182,183,184,188,192,193,196,198,200,202,204,206,207,209,211,213,223,226,228,230,232,233,234,239,241,243,244,246,249,252,257,265,270,274,277,282,283,284,285,287,289,292,294,297,299,301,302,303,305,306,308,311,313,315,316,318,320,323,327,332,340,342,344,347,348,349,351,352,353,354,356], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_04", "pdi_official", [257,349,353,361,363,365,367,369,371,373,377,382,384,387,389,391,393,395,398,400,403,405,408,410,412,414,416,417], "SPK-pdi-nar-06-stg-6-jetbridge-standoff", "review"),
    ("I-002_04", "other_passenger", [134,143,163,166,167,168,170,171,173,175,178,179,181,185,187,189,191,194,248,249,251,252,253], "SPK-pasajeros-del-vuelo-nar-06-stg-6-jetbridge-standoff", "auto"),
    ("I-002_04", "multi_party_audio", [260,263,265,270,274,277,283,284,285,287,289,292,294,295,296,297,301,302,303,305,306,308,311,313,315,316,318,320,323,327,329,332,335,336,340,342,344,347,348,349,351,352,353,354,356], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_04", "background_audio", [282,309], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_04", "unresolved_speaker", [30,31,172,174], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_05 ---
    ("I-002_05", "dgac_official", [4,5,7,8,9,10,12,13,16,18,19,29,32,33,34,36,71,74,75,76,77,78,79,81,82], "SPK-dgac-nar-07-stg-7-post-removal-investigation", "auto"),
    ("I-002_05", "pdi_official", [39,40,51,52,53,54,55,57,58,61,62,64,68,73,94,96,98,100,101,102,103,105,115,118,119,121,122,123,124,125,126,129,131,132,133,134,136,137,139,141,142,143,144,145,146,148,149,152,155,156,157,159,161,163,165,167,169,171,173,176,179,180,182], "SPK-pdi-nar-07-stg-7-post-removal-investigation", "auto"),
    ("I-002_05", "airline_staff", [38,45,56,59,60,63,65,66,69], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_05", "multi_party_audio", [30,37,41,42,43,44,46,47,48,49,50,58,62,69,70,71,72,82], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_05", "unresolved_speaker", [70], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_06 ---
    ("I-002_06", "airline_security_official", [0], "SPK-joaquin-barraza-latam-security", "auto"),
    ("I-002_06", "dgac_official", [3], "SPK-dgac-nar-07-stg-7-post-removal-investigation", "review"),
    ("I-002_06", "pdi_official", [1,2,5,13,14,17,18,38,40,42,43,45,46,62,63,64,76,77,79,89,90,92,93,101,102], "SPK-pdi-nar-stg-8-pdi-identity-control", "auto"),
    ("I-002_06", "multi_party_audio", [6,21,22,23,25,26,27,28,29,30,31,32,33,34,35,36,37,39,41,44,47,48,49,50,51,52,53,54,55,56,57,58,59,60,61,65,66,67,68,69,70,71,72,73,74,75,78,80,81,82,83,84,85,91,94,95,96,97,98,99,100,101,102,103,104,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_06", "background_audio", [86,87,88,99,100], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_06", "unresolved_speaker", [7,8,9,10,11,12,82,126], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_08 ---
    ("I-002_08", "unresolved_speaker", [22,29,34,39,41,44,48,60,62,80,86], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_09 ---
    ("I-002_09", "background_audio", [1,2], "SPK-background-nar-10-stg-16-counter-confrontation", "auto"),

    # --- I-002_10 ---
    ("I-002_10", "dgac_official", [0,1,3,5,7,9,10,12,16,18,20,22,24,26], "SPK-dgac-don-nicolas", "auto"),
    ("I-002_10", "airline_staff", [37,39,44,45,51,52,53,55,58,60,62,65,67,68,70,71,75,77,78,80,81,83,84,86,88,92,94,96,97,100,101,104,106,108,110,112,114,118,120,121,123,124,125,129,131,132,133,134,135,137,140,142,144,146,149,150,151,153,155,157,158,159,161,163,165,168,169,170,172,173,180], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_10", "airline_staff 2", [101,148], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_10A ---
    ("I-002_10A", "dgac_official", [0,7,11,12,14,15,16,18], "SPK-dgac-don-nicolas", "auto"),

    # --- I-002_11 ---
    ("I-002_11", "airline_staff", [0,2,4,10,13], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_11", "airline_security_official", [1,16,19,21,23,25,27,29,31,33,35,37,39,41,42,44,46,49,51,55,62,64,66,68,70,72,74], "SPK-joaquin-barraza-latam-security", "auto"),

    # --- I-002_12 ---
    ("I-002_12", "dgac_official", [0,3,6,8,9,10,12,13,15,17,18,20,22,24,26,29,31,32,33,34,36,38,39,41,43,47,48,50,52,54,55,57,58,60,61,62,66,68,70,72,73,75,76,78,80,82,84,86,87,88,90,91,92,93,94,96,97,98,99,101,103,104,105,106,107,108,109,110,111,112,113,114,115,117,118,119,120,121,122,123,124,125,127,128,129,130,131,132,133], "SPK-dgac-of-nar-15-stg-22-dgac-office", "auto"),
    ("I-002_12", "dgac_official 2", [121], "SPK-dgac-official-2-angry-one-nar-15-stg-22-dgac-office", "auto"),
    ("I-002_12", "dgac_official 3", [137,138,210,213], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_12", "dgac_EDGARDO", [136,167,169,211,220,221,222,223,227,230,232,235,238,239,242,243,245,247], "SPK-dgac-edgardo-ortiz", "auto"),
    ("I-002_12", "dgac_official_don_nicolas", [248,250,252,254,256,257,259,261,262,264,266,267,270,273,275,276,278,281,283,284,286,287,289,291,293,294,296,298,301,305,307,309], "SPK-dgac-don-nicolas", "auto"),

    # --- I-002_13 ---
    ("I-002_13", "airline_supervisor", [1,4,6,8,10,12,14,17,19,21], "SPK-diego-latam-supervisor", "auto"),

    # --- I-002_14 ---
    ("I-002_14", "dgac_edgardo_ortiz", [0,2,5,9,10,12,17,19,21,22,24,26,27,29,30,31,35,36,38,39,41,42,44], "SPK-dgac-edgardo-ortiz", "auto"),
    ("I-002_14", "DGAC_higher_official_Nicolas", [45,47,48,49,51,57,63,65,67,69,71,72,73,74,75], "SPK-dgac-don-nicolas", "auto"),
    ("I-002_14", "dgac_official", [59,61,62,77,79,80,81,87,95,96,97,99,101,103,105,106,108,109,111,113,114,115,117,119,121,122,123,124,125,127,129,130,131,133,134,135,139,143,144,151,153,154,155,156,157,159,160,162,163,164,165,167,168,169,170,171,174,175,177,179,180,181,182,183,184,185,187,189,192,193,194,195,196,197,199,201,202], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_14", "dgac_official 2", [121], "SPK-dgac-official-2-angry-one-nar-15-stg-22-dgac-office", "auto"),
    ("I-002_14", "dgac_official 3", [137,138,210,213], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_14", "dgac_EDGARDO", [136,167,169,211,220,221,222,223,227,230,232,235,238,239,242,243,245,247], "SPK-dgac-edgardo-ortiz", "auto"),
    ("I-002_14", "dgac_official_don_nicolas", [248,250,252,254,256,257,259,261,262,264,266,267,270,273,275,276,278,281,283,284,286,287,289,291,293,294,296,298,301,305,307,309], "SPK-dgac-don-nicolas", "auto"),
    ("I-002_14", "latam_staff_random", [314,318,321,325,328,333,335,337,338,340,343,348,350,352,354,357,359,366,367,370,371,374], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_16 ---
    ("I-002_16", "airline_supervisor", [0,1,3,5,8,10,11,16,18,20], "SPK-diego-latam-supervisor", "auto"),
    ("I-002_16", "other_passenger", [23], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_16", "unresolved_speaker", [13,14], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_17 ---
    ("I-002_17", "NEW_SPEAKER", [9], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_17", "airline_staff_antonella", [7,10,19], "SPK-antonela-latam-agent", "auto"),
    ("I-002_17", "airline_staff_3", [12,22], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_17", "airline_staff_4", [18,20,21], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_17", "airline_staff_5", [52,71], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_19 ---
    ("I-002_19", "airline_staff_antonella", [6,8], "SPK-antonela-latam-agent", "auto"),

    # --- I-002_20 ---
    ("I-002_20", "airline_supervisor_antonella", [3,10,16,17,22,25,29,30,33,35,37,42,47,49,50,52,54,57,59,61,62,75,78,80,82,84,85,88,90,99,102,104,106,108,110,114,116,118,121,123,125,127,129,131,133,135,137,139,140], "SPK-antonela-latam-agent", "auto"),
    ("I-002_20", "airline_staff_5", [4,43,46], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_20", "airline_staff", [6,8], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_21 ---
    ("I-002_21", "carabinero_official", [0,1,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,37,38,40,52,53,73,75,99,122,128,129,130,131,132,133,134,135,136,137,138,139,141,143,145,148,150,155,156,157,159,160,161], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_22 ---
    ("I-002_22", "carabinero_official", [0,1,3,4,6,8,10,12,13,14,23,34,36,37,42,47,49,51,54,57,59,61,62,67,68,70,72,76,77,78,79,80,81,82,83,84,85,86,87,88,89,90,91,92,93,94,95,96,97,99,100,101,102,103,105,106,107,108,109,110,111,112,113,114,115,116,117,118,119,120,121,122,123,124,125,126,127,128,129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,151,152,153,154,155,156,157,158,159,160,161,162,163,164,165,166,167,168,169,170,171,172,173,174,175,176,177,178,179,180,181,182,183,184,185,186,187,188,189,190,191,192,193,194,195,196,197,198,199,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,217,218,219,220,221,222,223,224,225], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_23 ---
    ("I-002_23", "carabinero_official", [0,1,14,16,22,28,32,34,39,41,44,46,48,50,62,63,64,65,66,67,68,70,73,77,81,83,85,86,87,88,89,90,92,95,97,99,101,103,107,111,112], "NEEDS_HUMAN_REVIEW", "review"),

    # --- I-002_24 ---
    ("I-002_24", "airline_supervisor", [4,5,6,9,11,13,15,17,19,21,24,26,28,30,32,35,39,41,44,47,49,52,54,56,58,65,68,70,82,103,105,113,114,121,126,127,129,131,137,140,142,145,147,242,244,246,249,253,264,265], "SPK-latam-supervisora-nar-19-stg-12", "auto"),
    ("I-002_24", "airline_staff", [50,65,66,68,70,78,80,82,90,92,94,96,98,102,107,109,110,112,114,154,171,172,174,181,183,187,205,206,208,209,211,214,216,218,219,220,223,225,227,232,234,235,238,239,241,243,245,247,252,269,271,272,273,274,275], "NEEDS_HUMAN_REVIEW", "review"),
    ("I-002_24", "unresolved_speaker", [276,277], "NEEDS_HUMAN_REVIEW", "review"),
]


def load_transcript(file_key: str) -> dict:
    """Load a transcript JSON by its short file key."""
    tid = TRANSCRIPT_ID_MAP.get(file_key)
    if not tid:
        return {}
    path = transcripts_dir / f"{tid}.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    patches = []
    stats = {"auto": 0, "review": 0, "not_found": 0}

    for (file_key, old_speaker, indices, suggested_id, confidence) in MAPPING_RULES:
        tid = TRANSCRIPT_ID_MAP.get(file_key)
        if not tid:
            print(f"Warning: No transcript ID mapping for '{file_key}'")
            continue

        data = load_transcript(file_key)
        segments = data.get("segments", [])
        seg_by_index = {s.get("index", i): s for i, s in enumerate(segments)}

        for idx in indices:
            seg = seg_by_index.get(idx)
            if seg is None:
                # Try by positional list index as fallback
                if idx < len(segments):
                    seg = segments[idx]

            actual_speaker = seg.get("speaker", "") if seg else None

            suggested_id, confidence = canonicalise(suggested_id, confidence)

            patch = {
                "transcript_id": tid,
                "segment_index": idx,
                "old_speaker": actual_speaker if actual_speaker is not None else old_speaker,
                "label_from_doc": old_speaker,
                "suggested_speaker_id": suggested_id,
                "confidence": confidence,
            }
            patches.append(patch)

            if actual_speaker is None:
                stats["not_found"] += 1
            elif confidence == "auto":
                stats["auto"] += 1
            else:
                stats["review"] += 1

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(patches, f, indent=2, ensure_ascii=False)

    total = len(patches)
    print("=" * 60)
    print("SPEAKER PATCH FILE GENERATED")
    print("=" * 60)
    print(f"Total patch entries    : {total}")
    print(f"  Auto-applicable      : {stats['auto']} (confidence=auto)")
    print(f"  Needs human review   : {stats['review']} (confidence=review)")
    print(f"  Segment not found    : {stats['not_found']}")
    print(f"Output                 : {output_file.relative_to(repo_root)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
