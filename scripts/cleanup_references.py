#!/usr/bin/env python3
"""Reconcile data/transcripts_by_audio/ to the rendered/ canonical naming.

Source of truth: /Users/.../INCIDENT_2024-07-05/transcripts/rendered/timeline_<NAME>.html
Backing data: data/LA8159_files/main_latam_case_version/ (= raw/, post-sync).

This script:
  1. Quarantines first_latam-only host dirs (no raw equivalent).
  2. Quarantines `aeropuerto_arturo_merino_benitez_*` dirs (duplicate of STG_*).
  3. Strips first_latam refs from mixed manifests.
  4. Adds Aeropuerto_Arturo_Merino_Beni_tez_29.json as a new version of aeropuerto_stg_29.
  5. Bootstraps host dirs for carabineros_ppdartnel_2 and carabineros_ppdartnel_3
     from raw Pedro_Pablo_Dartnell_{2,3}.json.

Reversible: all moved dirs go to data/transcripts_by_audio/_quarantine_<ts>/.
Default is dry-run; pass --apply to execute.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REFS = REPO_ROOT / "data" / "transcripts_by_audio"
MAIN = (REPO_ROOT / "data" / "LA8159_files" / "main_latam_case_version").resolve()
RAW_DEFAULT = Path(
    "/Users/leandrodisconzi/work/business/OliviaLegal/cases/INCIDENTS/"
    "INCIDENT_2024-07-05/transcripts/raw"
)
RENDERED_DEFAULT = Path(
    "/Users/leandrodisconzi/work/business/OliviaLegal/cases/INCIDENTS/"
    "INCIDENT_2024-07-05/transcripts/rendered"
)

# 22 alias dirs (Arturo Merino Benitez == STG airport); duplicates with no raw backing.
ALIAS_PREFIX = "aeropuerto_arturo_merino_benitez"

# Hosts that should be removed from manifests entirely (first_latam-only narrative aliases).
NARRATIVE_HOSTS = {
    "audio_12_full", "audio_22_full", "audio_3_full", "audio_4_full",
    "audio_7_plot_part_2",
    "boarding_gate_question_about_boarding", "boarding_gate_question_to_pilots",
    "dgac_contradictions_meet_jose",
    "inside_plane_1st_defamation_told_to_leave",
    "inside_plane_2nd_defamation_got_intimidated_to_leave_or_else",
    "inside_plane_publicly_blamed_for_delay_and_threatned_police_action",
    "masterplan_latam_sup_diego_strategizing_delete_traces_print_in_desk_upstairs",
    "nova_gravac_a_o_2", "nova_gravac_a_o_3", "nova_gravac_a_o_4", "nova_gravacao_2",
    "pdi_dgac_latam_resolve_to_use_brute_force",
    "pdi_outside_where_the_magic_happens",
    "pedro_pablo_dartnell",  # first_latam-only; raw Pedro_Pablo_Dartnell_{2,3} go under carabineros_ppdartnel_{2,3}
    "portaste_mal",
    "response_1748668067564",
    "t2_dgac_sends_to_latam_counter",
    "transcript_1748818294",
}


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _is_main_backed(symlink: Path) -> bool:
    if not symlink.is_symlink():
        return False
    target = (symlink.parent / os.readlink(symlink)).resolve()
    try:
        target.relative_to(MAIN)
        return True
    except ValueError:
        return False


def _classify_host(host: Path) -> dict:
    files = [p for p in host.iterdir() if p.is_file() and p.suffix == ".json" and p.name != "manifest.json"]
    main_files = [f for f in files if _is_main_backed(f)]
    other_files = [f for f in files if f not in main_files]
    return {"main": main_files, "other": other_files, "total": len(files)}


def _read_manifest(host: Path) -> dict | None:
    mf = host / "manifest.json"
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text())
    except Exception:
        return None


def _write_manifest(host: Path, data: dict, apply: bool) -> None:
    mf = host / "manifest.json"
    if apply:
        mf.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _ref_filename(version_entry: dict) -> str | None:
    # Manifests use {"file": "..."} or {"path": "..."} or {"filename": "..."}.
    for key in ("file", "filename", "path", "ref", "reference"):
        v = version_entry.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def strip_dangling(apply: bool) -> None:
    """Remove dangling symlinks under transcripts_by_audio/ and drop matching manifest entries."""
    if not REFS.exists():
        print(f"[abort] missing {REFS}", file=sys.stderr); sys.exit(2)

    ts = _ts()
    actions: list[tuple[Path, list[Path], dict | None, dict | None]] = []

    for host in sorted(REFS.iterdir()):
        if not host.is_dir() or host.name.startswith("_quarantine_"):
            continue
        broken: list[Path] = []
        for f in host.glob("*.json"):
            if f.name == "manifest.json":
                continue
            if f.is_symlink():
                target = (f.parent / os.readlink(f)).resolve()
                if not target.exists():
                    broken.append(f)
        if not broken:
            continue

        broken_basenames = {p.name for p in broken}
        mf = _read_manifest(host)
        new_mf: dict | None = None
        if mf is not None:
            key = "versions" if "versions" in mf else ("references" if "references" in mf else "versions")
            versions = mf.get(key) or []
            kept = [
                v for v in versions
                if Path(_ref_filename(v) or "").name not in broken_basenames
            ]
            if len(kept) != len(versions):
                new_mf = dict(mf)
                new_mf[key] = kept
        actions.append((host, broken, mf, new_mf))

    print(f"\n[plan strip-dangling] hosts affected: {len(actions)}")
    for host, broken, mf, new_mf in actions:
        for b in broken:
            print(f"   - unlink {host.name}/{b.name} -> {os.readlink(b)}")
        if new_mf is not None:
            kept_n = len(new_mf.get("versions") or new_mf.get("references") or [])
            total_n = len((mf or {}).get("versions") or (mf or {}).get("references") or [])
            print(f"   * rewrite {host.name}/manifest.json (versions {total_n} -> {kept_n})")

    if not apply:
        print("\n[dry-run] nothing applied. Re-run with --apply to execute.")
        return

    # ---- APPLY ----
    for host, broken, _, new_mf in actions:
        for b in broken:
            try:
                b.unlink()
                print(f"[unlinked] {host.name}/{b.name}")
            except Exception as e:
                print(f"  [warn] could not unlink {b}: {e}")
        if new_mf is not None:
            backup = host / f"manifest.json.bak_strip_{ts}"
            shutil.copy2(host / "manifest.json", backup)
            _write_manifest(host, new_mf, apply=True)
            print(f"[manifest] {host.name}: dropped dangling entries (backup: {backup.name})")

    # Final dangling check
    remaining = []
    for host in sorted(REFS.iterdir()):
        if not host.is_dir() or host.name.startswith("_quarantine_"):
            continue
        for f in host.glob("*.json"):
            if f.name == "manifest.json":
                continue
            if f.is_symlink() and not (f.parent / os.readlink(f)).resolve().exists():
                remaining.append(str(f.relative_to(REFS)))
    print(f"\n[post-apply] remaining dangling symlinks: {len(remaining)}")
    for d in remaining:
        print(f"   - {d}")


def plan_and_apply(apply: bool, raw_dir: Path, rendered_dir: Path) -> None:
    if not REFS.exists():
        print(f"[abort] missing {REFS}", file=sys.stderr); sys.exit(2)
    if not raw_dir.exists():
        print(f"[abort] missing raw dir {raw_dir}", file=sys.stderr); sys.exit(2)

    # 1. Identify rendered canonical names (just for reporting).
    canonical = []
    if rendered_dir.exists():
        for p in sorted(rendered_dir.glob("timeline_*.html")):
            canonical.append(p.stem.removeprefix("timeline_"))
    print(f"[info] rendered canonical names: {len(canonical)}")

    ts = _ts()
    quarantine_dir = REFS / f"_quarantine_{ts}"

    # 2. Build list of hosts to quarantine.
    to_quarantine: list[Path] = []
    for host in sorted(REFS.iterdir()):
        if not host.is_dir() or host.name.startswith("_quarantine_"):
            continue
        if host.name.startswith(ALIAS_PREFIX):
            to_quarantine.append(host); continue
        if host.name in NARRATIVE_HOSTS:
            to_quarantine.append(host); continue

    print(f"\n[plan] quarantine {len(to_quarantine)} host dirs -> {quarantine_dir}")
    for h in to_quarantine:
        print(f"   - {h.name}")

    # 3. Strip first_latam refs from mixed manifests (terminal_internacional_t2).
    mixed_strip: list[tuple[Path, dict]] = []
    for host in sorted(REFS.iterdir()):
        if not host.is_dir() or host in to_quarantine or host.name.startswith("_quarantine_"):
            continue
        cls = _classify_host(host)
        if cls["other"]:
            mf = _read_manifest(host)
            if mf is None: continue
            versions = mf.get("versions") or mf.get("references") or []
            non_main_filenames = {p.name for p in cls["other"]}
            new_versions = []
            dropped = []
            for v in versions:
                fn = _ref_filename(v)
                if fn and Path(fn).name in non_main_filenames:
                    dropped.append(fn); continue
                new_versions.append(v)
            if dropped:
                new_mf = dict(mf)
                if "versions" in new_mf: new_mf["versions"] = new_versions
                else: new_mf["references"] = new_versions
                mixed_strip.append((host, new_mf))
                print(f"\n[plan] strip first_latam refs from {host.name}: dropping {dropped}")

    # 4. Add Aeropuerto_Arturo_Merino_Beni_tez_29 as new version under aeropuerto_stg_29.
    stg29 = REFS / "aeropuerto_stg_29"
    add_amb29 = None
    amb29_src = raw_dir / "Aeropuerto_Arturo_Merino_Beni_tez_29.json"
    if stg29.is_dir() and amb29_src.exists():
        existing = {p.name for p in stg29.glob("*.json") if p.is_symlink()}
        if amb29_src.name not in existing:
            add_amb29 = (stg29, amb29_src)
            print(f"\n[plan] add new version under {stg29.name}: {amb29_src.name}")

    # 5. Bootstrap carabineros_ppdartnel_2/3 from raw Pedro_Pablo_Dartnell_{2,3}.
    new_hosts: list[tuple[str, Path]] = []
    for n in ("2", "3"):
        host_name = f"carabineros_ppdartnel_{n}"
        host_path = REFS / host_name
        src_raw = raw_dir / f"Pedro_Pablo_Dartnell_{n}.json"
        if host_path.exists():
            print(f"[skip] {host_name} already exists")
            continue
        if not src_raw.exists():
            print(f"[skip] raw {src_raw.name} missing"); continue
        new_hosts.append((host_name, src_raw))
        print(f"\n[plan] create new host {host_name}/ -> raw/{src_raw.name}")

    if not apply:
        print("\n[dry-run] nothing applied. Re-run with --apply to execute.")
        return

    # ---- APPLY ----
    quarantine_dir.mkdir(parents=False, exist_ok=False)
    for h in to_quarantine:
        dest = quarantine_dir / h.name
        shutil.move(str(h), str(dest))
        print(f"[moved] {h.name} -> {dest}")

    for host, new_mf in mixed_strip:
        backup = host / f"manifest.json.bak_{ts}"
        shutil.copy2(host / "manifest.json", backup)
        _write_manifest(host, new_mf, apply=True)
        # also remove the dangling first_latam symlink files
        cls = _classify_host(host)
        for f in cls["other"]:
            try: f.unlink()
            except Exception as e: print(f"  [warn] could not remove {f}: {e}")
        print(f"[manifest] {host.name}: stripped first_latam refs (backup: {backup.name})")

    if add_amb29:
        host, src_raw = add_amb29
        # Copy raw file into MAIN (it's already there from prior sync, but be safe).
        main_target = MAIN / src_raw.name
        if not main_target.exists():
            shutil.copy2(src_raw, main_target)
            print(f"[copied] {src_raw.name} -> {main_target}")
        # Create symlink in host dir.
        link = host / src_raw.name
        rel = os.path.relpath(main_target, host)
        os.symlink(rel, link)
        # Update manifest.
        mf = _read_manifest(host) or {"canonical_name": host.name, "versions": []}
        versions = mf.get("versions") or mf.get("references") or []
        versions.append({"file": src_raw.name, "label": "Aeropuerto_Arturo_Merino_Beni_tez variant"})
        if "versions" in mf or "versions" not in mf and "references" not in mf:
            mf["versions"] = versions
        else:
            mf["references"] = versions
        backup = host / f"manifest.json.bak_{ts}"
        shutil.copy2(host / "manifest.json", backup)
        _write_manifest(host, mf, apply=True)
        print(f"[added] {host.name}/{src_raw.name} (manifest backup: {backup.name})")

    for host_name, src_raw in new_hosts:
        host_path = REFS / host_name
        host_path.mkdir(parents=False, exist_ok=False)
        # Ensure file is present in MAIN
        main_target = MAIN / src_raw.name
        if not main_target.exists():
            shutil.copy2(src_raw, main_target)
            print(f"[copied] {src_raw.name} -> {main_target}")
        link = host_path / src_raw.name
        rel = os.path.relpath(main_target, host_path)
        os.symlink(rel, link)
        manifest = {
            "canonical_name": host_name,
            "versions": [{"file": src_raw.name, "label": "raw"}],
        }
        (host_path / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        )
        print(f"[bootstrapped] {host_name}/ with {src_raw.name}")

    # Final sanity: list dangling symlinks.
    dangling = []
    for host in sorted(REFS.iterdir()):
        if not host.is_dir() or host.name.startswith("_quarantine_"): continue
        for f in host.glob("*.json"):
            if f.is_symlink():
                target = (f.parent / os.readlink(f)).resolve()
                if not target.exists():
                    dangling.append(str(f.relative_to(REFS)))
    print(f"\n[post-apply] dangling symlinks: {len(dangling)}")
    for d in dangling: print(f"   - {d}")
    print(f"\n[done] quarantine dir: {quarantine_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, default=RAW_DEFAULT)
    ap.add_argument("--rendered", type=Path, default=RENDERED_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--strip-dangling",
        action="store_true",
        help="Remove dangling symlinks and matching manifest entries; skip the full cleanup plan.",
    )
    args = ap.parse_args()
    if args.strip_dangling:
        strip_dangling(apply=args.apply)
        return
    plan_and_apply(apply=args.apply, raw_dir=args.raw, rendered_dir=args.rendered)


if __name__ == "__main__":
    main()
