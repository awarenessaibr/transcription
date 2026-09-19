#!/usr/bin/env python3
"""
generate_speaker_md_files.py

Phase 1 + Phase 5: Audit, generate and **enrich** speaker MD files.

What it does
------------
1. Archives orphaned MD files to ``data/speakers/.archive/``.
2. Scans ``data/transcripts/*.json`` ``participants`` to learn which speakers
   exist and which transcripts they appear in.
3. Reads ``data/speaker_index.json`` (produced by ``generate_speaker_index_v3.py``)
   and merges the authoritative per-speaker mapping into each MD file:
     * ``transcripts_appearing`` — wikilinks to every transcript
     * ``appearances``           — per transcript: segment labels + segment indices
     * ``segment_count``         — total mapped segment instances
     * ``appearance_count``      — number of transcripts where the speaker appears
     * ``display_name`` / ``organization`` / ``identification_confidence``
       (only upgraded when the current value is empty or a placeholder)
4. Refreshes a machine-marked ``<!-- BEGIN:APPEARANCES -->`` block in the body so
   the mapping is also readable in Obsidian.

Non-destructive guarantees
--------------------------
* Hand-curated content (``key_statements``, bespoke prose, custom frontmatter
  keys, ``_provenance``) is never rewritten.
* Only the keys listed above plus the marked body block are managed.
* Re-running is idempotent: an unchanged file is not rewritten.

Frontmatter format note
-----------------------
``templates/speakers-registry.html`` parses frontmatter with a deliberately tiny
YAML subset (``parseYamlLite``) that does **not** support nested lists. Therefore
``appearances`` is emitted as a list of *flat scalar maps*; segment labels and
indices are joined into comma-separated strings.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO / "data" / "transcripts"
SPEAKERS_DIR = REPO / "data" / "speakers"
ARCHIVE_DIR = SPEAKERS_DIR / ".archive"
INDEX_FILE = REPO / "data" / "speaker_index.json"

NOW_UTC = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── ID merges: old_id → canonical_id ──────────────────────────────────────────
ID_MERGES: dict[str, str] = {
    "SPK-dgac-nicolas": "SPK-dgac-don-nicolas",
    # Pilot fragments kept as-is per user preference
}

# ── Orphaned files to archive ──────────────────────────────────────────────────
ORPHANED_FILES = [
    "SPK-carabinero-dartnell-male.md",  # no matching transcript ID
    "SPK-pdi-officer-1.md",             # broken ID: SPK-PDI-Felipeficer-1
    "SPK-pdi-felipe.md",                # legacy label, not in any transcript
]

# ── Infer metadata from speaker_id slug ───────────────────────────────────────
ORG_HINTS = {
    "latam": "LATAM Airlines",
    "stewardess": "LATAM Airlines",
    "pilot": "LATAM Airlines",
    "piloto": "LATAM Airlines",
    "cabin": "LATAM Airlines",
    "supervisor": "LATAM Airlines",
    "staff": "LATAM Airlines",
    "gate": "LATAM Airlines",
    "luggage": "LATAM Airlines",
    "antonela": "LATAM Airlines",
    "diego": "LATAM Airlines",
    "barraza": "LATAM Airlines",
    "joaquin": "LATAM Airlines",
    "ruiz": "LATAM Airlines",
    "dgac": "DGAC (Dirección General de Aeronáutica Civil)",
    "pdi": "PDI (Policía de Investigaciones de Chile)",
    "carabinero": "Carabineros de Chile",
    "female-carabinero": "Carabineros de Chile",
    "computer-officer": "Carabineros de Chile",
    "passenger": "self (Leandro Disconzi)",
    "leandro": "self (Leandro Disconzi)",
    "pasajeros": "fellow passengers",
    "background": "ambient",
}

CONF_HINTS = {
    "leandro": "confirmed",
    "passenger": "confirmed",
    "barraza": "confirmed",
    "joaquin": "confirmed",
    "ruiz": "confirmed",
    "diego": "confirmed",
    "edgardo": "partial",
    "antonela": "partial",
    "dominika": "partial",
    "dgac": "role-only",
    "pdi": "role-only",
    "carabinero": "role-only",
    "pasajeros": "role-only",
    "background": "role-only",
    "staff": "role-only",
    "gate": "role-only",
    "luggage": "role-only",
    "supervisor": "role-only",
    "boss": "role-only",
    "official": "role-only",
    "speaker": "unknown",
    "unresolved": "unknown",
    "review": "unknown",
}


def infer_org(spk_id: str) -> str:
    slug = spk_id.lower()
    for hint, org in ORG_HINTS.items():
        if hint in slug:
            return org
    return "Unknown"


def infer_conf(spk_id: str) -> str:
    slug = spk_id.lower()
    for hint, conf in CONF_HINTS.items():
        if hint in slug:
            return conf
    return "role-only"


def slug_to_display(spk_id: str) -> str:
    """Convert SPK-foo-bar-baz into a readable display name."""
    name = spk_id.removeprefix("SPK-")
    # Remove NAR/STG suffix noise: -nar-XX-stg-YY-...
    name = re.sub(r"-nar-\d+-.*", "", name)
    name = re.sub(r"-nar-[a-z].*", "", name)
    # Capitalise
    parts = name.replace("-", " ").title()
    return parts


# ══════════════════════════════════════════════════════════════════════════════
# Managed frontmatter keys
# ══════════════════════════════════════════════════════════════════════════════
KEY_APPEARANCES = "appearances"
KEY_TRANSCRIPTS = "transcripts_appearing"
KEY_SEGMENT_COUNT = "segment_count"
KEY_APPEARANCE_COUNT = "appearance_count"

# ── Body markers for the generated appearances table ──────────────────────────
BODY_BEGIN = "<!-- BEGIN:APPEARANCES -->"
BODY_END = "<!-- END:APPEARANCES -->"

PLACEHOLDER_VALUES = {
    "",
    "unknown",
    "unknown role",
    "role unspecified",
    "n/a",
    "tbd",
    "unspecified",
    "none",
}


# ══════════════════════════════════════════════════════════════════════════════
# Frontmatter block editor (no third-party YAML dependency)
# ══════════════════════════════════════════════════════════════════════════════
_FRONTMATTER_RE = re.compile(r"^\ufeff?---\r?\n([\s\S]*?)\r?\n---\r?\n?")
_TOP_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(.*)$")


def split_frontmatter(text: str) -> tuple[str, str] | None:
    """Return ``(frontmatter, body)`` or ``None`` when there is no frontmatter."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    return m.group(1), text[m.end():]


def parse_blocks(fm: str) -> list[list[str]]:
    """Split frontmatter into top-level blocks (key line + continuation lines)."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in fm.split("\n"):
        if _TOP_KEY_RE.match(line):
            if current is not None:
                blocks.append(current)
            current = [line]
        else:
            if current is None:
                current = []
            current.append(line)
    if current is not None:
        blocks.append(current)
    return blocks


def block_key(block: list[str]) -> str | None:
    if not block:
        return None
    m = _TOP_KEY_RE.match(block[0])
    return m.group(1) if m else None


def unquote(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def get_scalar(blocks: list[list[str]], key: str) -> str | None:
    for block in blocks:
        if block_key(block) == key:
            m = _TOP_KEY_RE.match(block[0])
            if m:
                return unquote(m.group(2).strip())
    return None


def set_block(blocks: list[list[str]], key: str, lines: list[str], after: str | None = None) -> None:
    """Replace the block for ``key`` in place, else insert after ``after``, else append."""
    for i, block in enumerate(blocks):
        if block_key(block) == key:
            blocks[i] = list(lines)
            return
    if after:
        for i, block in enumerate(blocks):
            if block_key(block) == after:
                blocks.insert(i + 1, list(lines))
                return
    blocks.append(list(lines))


def render_frontmatter(blocks: list[list[str]]) -> str:
    lines: list[str] = []
    for block in blocks:
        lines.extend(block)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines)


def quote(value) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def is_placeholder(value: str | None, also: set[str] | None = None) -> bool:
    if value is None:
        return True
    v = unquote(value).strip().lower()
    if v in PLACEHOLDER_VALUES:
        return True
    return bool(also) and v in {x.lower() for x in also}


def pick_index_value(candidate: str | None, fallback: str) -> str:
    """Prefer a real value from the index, else infer it from the id slug.

    The index emits ``organization: "Unknown"`` / ``identification_confidence:
    "unknown"`` whenever the speaker has no profile file yet. Those strings are
    **truthy**, so a plain ``or`` would adopt them and bake the placeholder into
    the file being created — and every later index run would then read it back,
    making the placeholder permanent. Treat placeholder values as absent.

    >>> pick_index_value("PDI (Policía de Investigaciones de Chile)", "inferred")
    'PDI (Policía de Investigaciones de Chile)'
    >>> pick_index_value("Unknown", "inferred")
    'inferred'
    >>> pick_index_value("unknown", "inferred")
    'inferred'
    >>> pick_index_value(None, "inferred")
    'inferred'
    >>> pick_index_value("", "inferred")
    'inferred'
    """
    return fallback if is_placeholder(candidate) else str(candidate)


# ══════════════════════════════════════════════════════════════════════════════
# Managed block builders
# ══════════════════════════════════════════════════════════════════════════════
def transcript_lines(transcripts: list[str]) -> list[str]:
    lines = [f"{KEY_TRANSCRIPTS}:"]
    for tid in sorted(set(transcripts)):
        lines.append(f'  - "[[{tid}]]"')
    return lines


def appearance_lines(appearances: list[dict]) -> list[str]:
    """Emit a list of *flat scalar maps* (see module docstring)."""
    if not appearances:
        # A bare key parses to '' in the mini YAML parser, which is falsy and
        # therefore safe for `(sp.appearances || [])` style fallbacks.
        return [f"{KEY_APPEARANCES}:"]

    lines = [f"{KEY_APPEARANCES}:"]
    for app in appearances:
        tid = app.get("transcript_id") or ""
        labels = app.get("segment_labels") or []
        indices = app.get("segment_indices") or []
        lines.append(f"  - transcript_id: {quote(tid)}")
        lines.append(f"    segment_labels: {quote(', '.join(str(x) for x in labels))}")
        lines.append(f"    segment_indices: {quote(', '.join(str(x) for x in indices))}")
        lines.append(f"    segment_count: {quote(len(indices))}")
    return lines


def body_appearance_block(appearances: list[dict]) -> str:
    """Human-readable appearances table for the MD body."""
    out = [BODY_BEGIN, "## Appearances", ""]
    if not appearances:
        out.append("*No indexed segment appearances recorded yet.*")
        out.append(BODY_END)
        return "\n".join(out)

    total = sum(len(a.get("segment_indices") or []) for a in appearances)
    out.append(f"**{len(appearances)} transcript(s) · {total} mapped segment instance(s)**")
    out.append("")
    out.append("| Transcript | Segments | Labels |")
    out.append("| --- | --- | --- |")
    for app in appearances:
        tid = app.get("transcript_id") or "—"
        indices = app.get("segment_indices") or []
        labels = app.get("segment_labels") or []
        seg_cell = str(len(indices))
        if indices:
            preview = ", ".join(str(i) for i in indices[:12])
            if len(indices) > 12:
                preview += ", …"
            seg_cell = f"{len(indices)} <br><code>{preview}</code>"
        label_cell = ", ".join(f"`{l}`" for l in labels) if labels else "—"
        out.append(f"| [[{tid}]] | {seg_cell} | {label_cell} |")
    out.append("")
    out.append(BODY_END)
    return "\n".join(out)


def upsert_marked_block(body: str, block: str) -> str:
    pattern = re.compile(
        re.escape(BODY_BEGIN) + r"[\s\S]*?" + re.escape(BODY_END) + r"\n?",
        re.MULTILINE,
    )
    payload = block.rstrip() + "\n"
    if pattern.search(body):
        return pattern.sub(lambda _m: payload, body, count=1)

    anchor = "## Key Statements"
    if anchor in body:
        idx = body.index(anchor)
        return body[:idx] + payload + "\n" + body[idx:]
    return body.rstrip() + "\n\n" + payload


def refresh_transcripts_row(body: str, transcripts: list[str]) -> str:
    """Keep the ``| Transcripts | ... |`` table row in sync."""
    joined = ", ".join(f"[[{t}]]" for t in sorted(set(transcripts)))
    pattern = re.compile(r"^\|\s*Transcripts\s*\|.*$", re.MULTILINE)
    if pattern.search(body):
        return pattern.sub(lambda _m: f"| Transcripts | {joined} |", body, count=1)
    return body


def appearance_count(appearances: list[dict]) -> int:
    return len(appearances)


def segment_count(appearances: list[dict]) -> int:
    return sum(len(a.get("segment_indices") or []) for a in appearances)


def build_md(
    spk_id: str,
    participants: list[dict],
    transcripts: list[str],
    index_entry: dict | None = None,
    appearances: list[dict] | None = None,
) -> str:
    display = slug_to_display(spk_id)
    org = pick_index_value((index_entry or {}).get("organization"), infer_org(spk_id))
    conf = pick_index_value(
        (index_entry or {}).get("identification_confidence"), infer_conf(spk_id)
    )

    # Collect canonical names from participants
    canon_names = list({p.get("canonical_name", "") for p in participants if p.get("canonical_name")})
    display_name = pick_index_value(
        (index_entry or {}).get("display_name"),
        canon_names[0] if canon_names else display,
    )

    # Collect roles
    roles = list({p.get("role", "") for p in participants if p.get("role")})
    role_str = roles[0] if roles else "Unknown role"

    # Collect aliases from speaker_label values
    aliases = list({p.get("speaker_label", "") for p in participants if p.get("speaker_label")})
    appearances = list(appearances or [])
    alias_lines = "\n".join(f'  - "{a}"' for a in sorted(set(aliases)) if a)

    frontmatter = [
        "note_type: speaker",
        f"speaker_id: {spk_id}",
        f"display_name: {quote(display_name)}",
        f"role: {quote(role_str)}",
        f"organization: {quote(org)}",
        f"identification_confidence: {conf}",
        "incidents:",
        '  - "I-002"',
        *transcript_lines(transcripts),
        *appearance_lines(appearances),
        f"{KEY_APPEARANCE_COUNT}: {quote(appearance_count(appearances))}",
        f"{KEY_SEGMENT_COUNT}: {quote(segment_count(appearances))}",
        "key_statements: []",
        "tags:",
        "  - speaker",
        f"  - identification/{conf}",
        "aliases:",
        alias_lines if alias_lines else "  []",
        'classification: "Attorney Work Product — Privileged and Confidential"',
        "_provenance:",
        "  source_vault: vault-2026",
        f'  generated_utc: "{NOW_UTC}"',
        '  notes: "Auto-generated from data/transcripts/ + data/speaker_index.json. Hand-review key_statements."',
    ]

    body = f"""# {display_name} — {role_str}

| Field | Value |
|---|---|
| Organization | {org} |
| Identification | {conf} |
| Incidents | I-002 |
| Transcripts | {", ".join(f"[[{t}]]" for t in sorted(set(transcripts)))} |

## Key Statements

*No key statements recorded yet — review transcript segments.*

## Aliases

{chr(10).join(f"- `{a}`" for a in sorted(set(aliases)) if a)}
"""

    body = upsert_marked_block(body, body_appearance_block(appearances))
    return "---\n" + "\n".join(frontmatter) + "\n---\n\n" + body


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
def load_index() -> tuple[dict, dict]:
    """Return ``(index, mapped_speakers)``; empty dicts when unavailable."""
    if not INDEX_FILE.exists():
        print(f"[warn] {INDEX_FILE.relative_to(REPO)} not found — enrichment skipped")
        return {}, {}
    try:
        index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[warn] could not parse {INDEX_FILE.name}: {exc}")
        return {}, {}
    return index, (index.get("mapped_speakers") or {})


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich and generate speaker MD files")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files")
    args = parser.parse_args()

    SPEAKERS_DIR.mkdir(exist_ok=True)
    ARCHIVE_DIR.mkdir(exist_ok=True)

    # ── Step 1: Archive orphaned files ────────────────────────────────────────
    for fname in ORPHANED_FILES:
        src = SPEAKERS_DIR / fname
        if src.exists():
            dst = ARCHIVE_DIR / fname
            if not args.dry_run:
                shutil.move(str(src), str(dst))
            print(f"[archive] {fname}")

    # ── Step 2: Collect all speaker data from transcripts ─────────────────────
    # {spk_id: {participants: [...], transcripts: [...]}}
    speaker_data: dict[str, dict] = {}

    for f in sorted(TRANSCRIPTS_DIR.glob("*.json")):
        if f.name.endswith(".bak"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        tid = data.get("transcript_id", f.stem)

        for p in data.get("participants", []):
            raw_id = p.get("speaker_id", "")
            if not raw_id:
                continue
            # Apply ID merges
            spk_id = ID_MERGES.get(raw_id, raw_id)

            entry = speaker_data.setdefault(spk_id, {"participants": [], "transcripts": []})
            entry["participants"].append(p)
            if tid not in entry["transcripts"]:
                entry["transcripts"].append(tid)

    print(f"\nFound {len(speaker_data)} unique speaker IDs in data/transcripts/")

    # ── Step 3: Load the authoritative speaker index ──────────────────────────
    index, mapped = load_index()
    if mapped:
        print(f"Loaded {len(mapped)} mapped speaker(s) from {INDEX_FILE.relative_to(REPO)}")

    # Speakers known to the index but absent from the transcript scan still get
    # their MD file created/refreshed.
    for spk_id in mapped:
        speaker_data.setdefault(spk_id, {"participants": [], "transcripts": []})

    created = updated = skipped = 0

    for spk_id in sorted(speaker_data):
        info = speaker_data[spk_id]
        index_entry = mapped.get(spk_id)
        appearances = [dict(a) for a in ((index_entry or {}).get("appearances") or [])]

        # Guarantee every appearance exposes a transcript_id; transcripts seen in
        # the participant scan but missing from the index are added as bare rows.
        indexed_tids = {a.get("transcript_id") for a in appearances if a.get("transcript_id")}
        for tid in info["transcripts"]:
            if tid not in indexed_tids:
                appearances.append({"transcript_id": tid, "segment_labels": [], "segment_indices": []})

        transcripts = sorted(
            {a.get("transcript_id") for a in appearances if a.get("transcript_id")}
            or set(info["transcripts"])
        )
        n_appearances = appearance_count(appearances)
        n_segments = segment_count(appearances)

        md_path = SPEAKERS_DIR / f"{spk_id}.md"

        # ── Existing file: merge managed keys, preserve everything else ───────
        if md_path.exists():
            content = md_path.read_text(encoding="utf-8")
            parts = split_frontmatter(content)
            if parts is None:
                print(f"[skip]    {spk_id}.md — no frontmatter, left untouched")
                skipped += 1
                continue

            fm_raw, body = parts
            blocks = parse_blocks(fm_raw)

            set_block(blocks, KEY_TRANSCRIPTS, transcript_lines(transcripts))
            set_block(blocks, KEY_APPEARANCES, appearance_lines(appearances), after=KEY_TRANSCRIPTS)
            set_block(blocks, KEY_APPEARANCE_COUNT,
                      [f"{KEY_APPEARANCE_COUNT}: {quote(n_appearances)}"], after=KEY_APPEARANCES)
            set_block(blocks, KEY_SEGMENT_COUNT,
                      [f"{KEY_SEGMENT_COUNT}: {quote(n_segments)}"], after=KEY_APPEARANCE_COUNT)

            # Upgrade metadata only when the current value is empty/placeholder.
            if index_entry:
                slug_display = slug_to_display(spk_id)
                for key, candidate in (
                    ("display_name", index_entry.get("display_name")),
                    ("organization", index_entry.get("organization")),
                    ("identification_confidence", index_entry.get("identification_confidence")),
                ):
                    if not candidate:
                        continue
                    if is_placeholder(get_scalar(blocks, key), also={slug_display}):
                        set_block(blocks, key, [f"{key}: {quote(candidate)}"])

            new_body = refresh_transcripts_row(body, transcripts)
            new_body = upsert_marked_block(new_body, body_appearance_block(appearances))

            new_content = "---\n" + render_frontmatter(blocks) + "\n---\n\n" + new_body.lstrip("\n")

            if new_content != content:
                if not args.dry_run:
                    md_path.write_text(new_content, encoding="utf-8")
                print(f"[update]  {spk_id}.md — {n_appearances} appearance(s), {n_segments} segment(s)")
                updated += 1
            else:
                print(f"[ok]      {spk_id}.md")
                skipped += 1

        # ── New file: full skeleton including the enriched mapping ───────────
        else:
            md_content = build_md(spk_id, info["participants"], transcripts, index_entry, appearances)
            if not args.dry_run:
                md_path.write_text(md_content, encoding="utf-8")
            print(f"[create]  {spk_id}.md")
            created += 1

    print(f"\n{'=' * 58}")
    print(f"Index entries       : {len(mapped)}")
    if index:
        summary = index.get("summary", {})
        print(f"Index generated     : {summary.get('generated_utc', '?')}")
        print(f"Segments in index   : {summary.get('total_segments_scanned', '?')}")
    print(f"Created             : {created}")
    print(f"Updated             : {updated}")
    print(f"Unchanged           : {skipped}")
    print(f"Total MD files now  : {len(list(SPEAKERS_DIR.glob('*.md')))}")
    if args.dry_run:
        print("\n(dry-run: no files were written)")


if __name__ == "__main__":
    main()
