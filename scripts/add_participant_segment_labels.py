#!/usr/bin/env python3
"""
add_participant_segment_labels.py

Updates each transcript's participants[] to add a `segment_labels` field —
the list of segment speaker labels used by that participant in this specific transcript.

This bridges the gap between:
  - participants[].speaker_label: "Supervisora Antonela"  (descriptive, for readers)
  - segment.speaker: "airline_supervisor"  (normalized role label, for indexing)

Mapping source: provided by analysis of transcripts — the segment labels are
generic role labels that correspond to each participant by process of elimination
(usually 2 speakers per transcript, or clearly named labels like 'airline_staff_antonella').

After this script runs, qdrant_index.py and generate_speaker_index_v3.py can
use `participants[].segment_labels` to match segments to speaker_ids.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO / "data" / "transcripts"

# Hand-curated mapping: transcript_id → {speaker_id: [segment_labels]}
# Built by analyzing the label coverage gaps output.
# Rules:
#   - "passenger" always → SPK-passenger-leandro
#   - Generic role labels → resolved by process of elimination per transcript
SEGMENT_LABEL_MAP: dict[str, dict[str, list[str]]] = {
    "I-002_01_NAR-01_STG_1_pre_boarding": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-latam-pilot-ruiz-nar-01-stg-1-pre-boarding": ["airline_staff", "airline_pilot"],
    },
    "I-002_02_NAR-02_STG_2_boarding_gate": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-latam-gate-staff-nar-02-stg-2-boarding-gate": ["airline_staff"],
        "SPK-latam-gate-staff-acuser-nar-02-stg-2-boarding-gate": ["airline_staff_acuser", "airline_staff (Acuser)"],
        "SPK-latam-gate-staff-2-nar-02-stg-2-boarding-gate": ["airline_staff_2"],
        "SPK-piloto-ruiz-nar-02-stg-2-boarding-gate": ["airline_pilot"],
    },
    "I-002_03_NAR-05_STG_5_aircraft_removal": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-stewardess-accuser": ["airline_cabin_crew"],
    },
    "I-002_04_NAR-06_STG_6_jetbridge_standoff": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-pdi-nar-06-stg-6-jetbridge-standoff": ["pdi_official"],
        "SPK-dgac-nar-06-stg-6-jetbridge-standoff": ["dgac_official"],
        "SPK-pilot-ruiz": ["airline_pilot", "airline_cabin_crew"],
        "SPK-pasajeros-del-vuelo-nar-06-stg-6-jetbridge-standoff": ["other_passengers", "other_passenger"],
        "SPK-joaquin-barraza-latam-security": ["airline_security_official"],
    },
    "I-002_05B_NAR-11_STG_11_waiting_area": {
        "SPK-passenger-leandro": ["passenger"],
    },
    "I-002_05_NAR-07_STG_7_post_removal_investigation": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-pdi-nar-07-stg-7-post-removal-investigation": ["pdi_official"],
        "SPK-dgac-nar-07-stg-7-post-removal-investigation": ["dgac_official"],
        "SPK-latam-staff-acuser-nar-07-stg-7-post-removal-investigation": ["airline_staff"],
        "SPK-latam-boss-nar-07-stg-7-post-removal-investigation": ["airline_supervisor"],
    },
    "I-002_06_NAR-STG_8_pdi_identity_control": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-pdi-nar-stg-8-pdi-identity-control": ["pdi_official", "airline_security_official", "dgac_official"],
        "SPK-pdi-female-nar-stg-8-pdi-identity-control": ["pdi_female"],
        "SPK-pdi-2-nar-stg-8-pdi-identity-control": ["pdi_2"],
    },
    "I-002_07_NAR-06_STG_13_post_PDI_corridor": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-joaquin-barraza-latam-security": [
            "airline_security_official", "airline_luggage_staff",
            "pdi_official", "dgac_official",
        ],
    },
    "I-002_08_NAR-09_STG_15_luggage_recovery": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-latam-luggage-supervisor-dominika-nar-09-stg-15-luggage-recovery": ["airline_luggage_staff"],
    },
    "I-002_09_NAR-10_STG_16_counter_confrontation": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-joaquin-barraza-latam-security": ["airline_security_official"],
        "SPK-background-nar-10-stg-16-counter-confrontation": ["background_audio"],
    },
    "I-002_10A_NAR-19_STG_19_counter_escalation": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-dgac-don-nicolas": ["dgac_official"],
    },
    "I-002_10B_NAR-18_STG_18_counter_fragment": {
        "SPK-passenger-leandro": ["passenger"],
    },
    "I-002_10_NAR-14_Terminal_Internacional_T2_counter": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-dgac-don-nicolas-nar-14-terminal-internacional-t2-counter": ["dgac_official"],
        "SPK-latam-staff-counter-nar-14-terminal-internacional-t2-counter": ["airline_staff"],
        "SPK-latam-staff-counter-2-nar-14-terminal-internacional-t2-counter": ["airline_staff 2"],
        "SPK-latam-staff-counter-female-nar-14-terminal-internacional-t2-counter": ["airline_staff_female"],
    },
    "I-002_11_NAR-13_STG_20_barraza_counter": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-joaquin-barraza-latam-security": ["airline_security_official", "airline_staff"],
    },
    "I-002_12_NAR-15_STG_22_DGAC_office": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-dgac-edgardo-ortiz": ["dgac_official"],
        "SPK-dgac-official-1-nar-15-stg-22-dgac-office": ["dgac_official_1"],
        "SPK-dgac-official-2-nar-15-stg-22-dgac-office": ["dgac_official_2"],
    },
    "I-002_13_NAR-18_STG_26_self_narration": {
        "SPK-passenger-leandro": ["passenger", "airline_supervisor"],  # self-narration only
    },
    "I-002_14_NAR-16_STG_23_DGAC_don_nicolas": {
        "SPK-passenger-leandro": ["passenger", "passanger"],
        "SPK-dgac-don-nicolas-nar-16-stg-23-dgac-don-nicolas": [
            "dgac_official_don_nicolas", "DGAC_higher_official_Nicolas", "dgac_official"],
        "SPK-dgac-edgardo-ortiz-nar-16-stg-23-dgac-don-nicolas": [
            "dgac_edgardo_ortiz", "dgac_EDGARDO", "dgac_official_Edgardo", "dgac_official 2"],
        "SPK-dgac-official-3-nar-16-stg-23-dgac-don-nicolas": ["dgac_official 3"],
        "SPK-latam-staff-random-nar-16-stg-23-dgac-don-nicolas": ["latam_staff_random"],
    },
    "I-002_15_NAR-19_STG_27_self_narration": {
        "SPK-passenger-leandro": ["passenger", "airline_supervisor"],  # self-narration only
    },
    "I-002_16_NAR-20_STG_28": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-diego-latam-supervisor": ["airline_supervisor"],
        "SPK-pasajeros-del-vuelo-nar-06-stg-6-jetbridge-standoff": ["other_passenger"],
    },
    "I-002_17_NAR-21_STG_29": {
        "SPK-passenger-leandro": ["passenger", "passengerairline_supervisor"],
        "SPK-diego-latam-supervisor": ["airline_supervisor", "airline_staff_3", "airline_staff_4", "airline_staff_5", "NEW_SPEAKER"],
        "SPK-antonela-latam-agent": ["airline_staff_antonella"],
    },
    "I-002_18_NAR_LATAM_STG_2": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-antonela-latam-agent": ["airline_supervisor"],
    },
    "I-002_19_NAR_LATAM_STG_3": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-antonela-latam-agent": ["airline_staff_antonella"],
    },
    "I-002_20_NAR_LATAM_STG_4": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-antonela-latam-agent": ["airline_supervisor_antonella"],
        "SPK-latam-staff-speaker-01-nar-latam-stg-4": ["airline_staff", "airline_staff_5"],
    },
    "I-002_21_NAR_CARABINEROS_1": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-female-carabinero-2-nar-carabineros-1": ["carabinero_official"],
        "SPK-computer-officer-nar-carabineros-1": ["carabinero_computer_officer"],
        "SPK-carabinero-constancia-nar-carabineros-1": ["carabinero_constancia"],
    },
    "I-002_22_NAR_CARABINEROS_2": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-female-carabinero-2-nar-carabineros-2": ["carabinero_official"],
        "SPK-computer-officer-nar-carabineros-2": ["carabinero_computer_officer"],
    },
    "I-002_23_NAR_CARABINEROS_3": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-female-carabinero-2-nar-carabineros-3": ["carabinero_official"],
        "SPK-carabinero-speaker-00-nar-carabineros-3": ["carabinero_speaker_00"],
    },
    "I-002_24_NAR-19_STG_12": {
        "SPK-passenger-leandro": ["passenger"],
        "SPK-latam-supervisora-nar-19-stg-12": ["airline_supervisor"],
        "SPK-latam-official-nar-19-stg-12": ["airline_official"],
        "SPK-latam-staff-nar-19-stg-12": ["airline_staff"],
    },
}


def main() -> None:
    updated = 0
    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        if f.name.endswith(".bak"):
            continue

        data = json.loads(f.read_text(encoding="utf-8"))
        tid = data.get("transcript_id", f.stem)

        tid_map = SEGMENT_LABEL_MAP.get(tid)
        if not tid_map:
            print(f"[skip]   {tid} — no label map defined")
            continue

        changed = False
        participants = data.get("participants", [])
        for p in participants:
            spk_id = p.get("speaker_id")
            if not spk_id:
                continue
            labels = tid_map.get(spk_id)
            if labels is not None:
                existing = p.get("segment_labels", [])
                if existing != labels:
                    p["segment_labels"] = labels
                    changed = True

        if changed:
            bak = f.with_suffix(".json.bak")
            if not bak.exists():
                bak.write_bytes(f.read_bytes())
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            updated += 1
            print(f"[update] {tid}")
        else:
            print(f"[ok]     {tid}")

    print(f"\nUpdated {updated} transcripts with segment_labels")


if __name__ == "__main__":
    main()
