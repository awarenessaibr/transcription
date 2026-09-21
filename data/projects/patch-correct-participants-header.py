import json

# Load corrected transcript
with open("I-002_06_NAR-STG_8_pdi_identity_control.corrected.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# Map segment labels to canonical IDs and metadata
label_to_canonical = {
    "passenger": {
        "speaker_id": "SPK-passenger-leandro",
        "canonical_name": "Leandro Disconzi",
        "role": "Passenger",
    },
    "PDI": {
        "speaker_id": "SPK-pdi",
        "canonical_name": "PDI",
        "role": "PDI Officer",
    },
    "pdi_official": {
        "speaker_id": "SPK-pdi",
        "canonical_name": "PDI",
        "role": "PDI Officer",
    },
    "PDI-Female": {
        "speaker_id": "SPK-pdi-female",
        "canonical_name": "PDI Female",
        "role": "PDI Female Officer",
    },
    "PDI-Female 2": {
        "speaker_id": "SPK-pdi-female-2",
        "canonical_name": "PDI Female 2",
        "role": "PDI Female Officer",
    },
    "DGAC": {
        "speaker_id": "SPK-dgac",
        "canonical_name": "DGAC",
        "role": "DGAC Official",
    },
    "dgac_official": {
        "speaker_id": "SPK-dgac",
        "canonical_name": "DGAC",
        "role": "DGAC Official",
    },
    "Joaquin Barraza": {
        "speaker_id": "SPK-joaquin-barraza-latam-security",
        "canonical_name": "Joaquín Barraza",
        "role": "LATAM Security Chief",
    },
    "airline_security_official": {
        "speaker_id": "SPK-joaquin-barraza-latam-security",
        "canonical_name": "Joaquín Barraza",
        "role": "LATAM Security Chief",
    },
    "Chilean Officers": {
        "speaker_id": "SPK-chilean-officers",
        "canonical_name": "Chilean Officers",
        "role": "Law enforcement / airport officials",
    },
    "background_audio": {
        "speaker_id": "SPK-background",
        "canonical_name": "Background audio",
        "role": "Ambient",
    },
}

# 1. Normalise every segment to canonical speaker_id
for seg in data["segments"]:
    label = seg.get("speaker")
    if label in label_to_canonical:
        seg["speaker_id"] = label_to_canonical[label]["speaker_id"]
    else:
        seg["speaker_id"] = None  # or raise / log

# 2. Collect canonical IDs and their metadata
canonical_ids = {}
for seg in data["segments"]:
    sid = seg.get("speaker_id")
    if not sid:
        continue
    if sid not in canonical_ids:
        # find original label to get metadata
        label = seg.get("speaker")
        meta = label_to_canonical.get(label, {})
        canonical_ids[sid] = {
            "canonical_name": meta.get("canonical_name", "Unknown"),
            "role": meta.get("role", "Unknown"),
            "speaker_label": meta.get("canonical_name", sid),  # or use sid
            "speaker_id": sid,
            "segment_labels": [],
        }
    # aggregate original labels as segment_labels
    orig_label = seg.get("speaker")
    if orig_label and orig_label not in canonical_ids[sid]["segment_labels"]:
        canonical_ids[sid]["segment_labels"].append(orig_label)

# 3. Build new participants array
new_participants = []
for sid, entry in canonical_ids.items():
    new_participants.append({
        "canonical_name": entry["canonical_name"],
        "role": entry["role"],
        "speaker_label": entry["speaker_label"],
        "speaker_id": entry["speaker_id"],
        "segment_labels": entry["segment_labels"],
    })

# 4. Replace participants
data["participants"] = new_participants

# 5. Write out
with open("I-002_06_NAR-STG_8_pdi_identity_control.fixed.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)