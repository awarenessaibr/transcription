#!/usr/bin/env python3
"""Write the four-sub-report law registry (schema v2).

Produces a ``law_registry.v2.json`` conforming to
``data/law/schemas/law_registry.v2.schema.json``: four independently-gated
sub-reports instead of the single ``validation_ok`` boolean.

The default output is a **new** file, not ``law_registry.json``. The v2 document
is not a superset of v1 — it drops ``summary.data_law_md_files``,
``files[].articles_in_qdrant`` / ``in_qdrant_eli`` / ``alias_eli`` /
``missing_eli`` / ``source_basename_present_in_qdrant``, ``qdrant_only_articles``
and ``detail`` — all of which ``templates/law-registry.html`` and
``src/presentation/routers/law_registry.py`` read. Point ``--output`` at the
tracked file only once those consumers have been migrated.

Examples
--------
    # corpus-only verdict (no network); identity gate is still authoritative
    python scripts/build_law_registry_v2.py --offline

    # full four-sub-report run against the live collection
    python scripts/build_law_registry_v2.py

    # prove determinism and validate against the JSON Schema
    python scripts/build_law_registry_v2.py --check-determinism --validate-schema

    # replace the tracked v1 registry (only after the UI/API are migrated)
    python scripts/build_law_registry_v2.py --output data/law/_mapping/law_registry.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.infrastructure.law_registry_v2 import (  # noqa: E402
    build_v2_registry,
    collect_variants,
)
from src.infrastructure.qdrant_law_index import (  # noqa: E402
    CANONICAL_COLLECTION,
    LawCorpusParser,
    _scroll_all,
    build_qdrant_client,
    default_law_dir,
)

DEFAULT_OUTPUT = "data/law/_mapping/law_registry.v2.json"
SCHEMA_PATH = "data/law/schemas/law_registry.v2.schema.json"


def _load_env() -> None:
    """Same .env files as ``src.config``, without importing torch."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    shared = REPO_ROOT.parent / "_shared" / ".env"
    local = REPO_ROOT / ".env"
    if shared.exists():
        load_dotenv(shared, override=False)
    if local.exists():
        load_dotenv(local, override=True)


def _validate(document: dict[str, Any], schema_file: Path) -> list[str]:
    """Return a list of schema violations (empty means valid)."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover
        return ["jsonschema is not installed; skipped schema validation"]

    schema = json.loads(schema_file.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}" for e in errors]


def _without_timestamp(document: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in document.items() if k != "generated_at"}, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--law-dir", default=None, help="corpus root (default: <repo>/data/law)")
    parser.add_argument("--collection", default=CANONICAL_COLLECTION, help="collection to read for coverage")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"where to write the report (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--offline", action="store_true", help="do not contact Qdrant; skip coverage/provenance/fidelity")
    parser.add_argument("--sample", type=int, default=None, help="cap the per-point arrays (totals stay complete)")
    parser.add_argument("--prefer-language", default="en", help="canonical locale the ingester prefers")
    parser.add_argument("--check-determinism", action="store_true", help="build twice and require byte-identical output")
    parser.add_argument("--validate-schema", action="store_true", help="validate the document against the JSON Schema")
    parser.add_argument("--allow-fail", action="store_true", help="exit 0 even when gates.overall != pass")
    parser.add_argument("--json", action="store_true", help="print the document to stdout")
    args = parser.parse_args(argv)

    root = Path(args.law_dir).resolve() if args.law_dir else default_law_dir()
    plan = LawCorpusParser(preferred_language=args.prefer_language).build_plan(root)
    variants = collect_variants(root)

    live_records = None
    if not args.offline:
        _load_env()
        url = os.getenv("QDRANT_URL")
        api_key = os.getenv("QDRANT_API_KEY")
        if not url:
            print("error: QDRANT_URL is not set; re-run with --offline", file=sys.stderr)
            return 2
        client = build_qdrant_client(url, api_key)
        try:
            live_records = _scroll_all(client, args.collection)
        finally:
            client.close()

    document = build_v2_registry(
        plan,
        collection=args.collection,
        root=root,
        live_records=live_records,
        variants_by_eli=variants,
        sample=args.sample,
    )

    if args.check_determinism:
        again = build_v2_registry(
            plan,
            collection=args.collection,
            root=root,
            live_records=live_records,
            variants_by_eli=variants,
            sample=args.sample,
            generated_at=document["generated_at"],
        )
        if _without_timestamp(document) != _without_timestamp(again):
            print("error: two builds differ (non-deterministic output)", file=sys.stderr)
            return 2
        print("determinism: two builds are identical (excluding generated_at)", file=sys.stderr)

    if args.validate_schema:
        schema_file = REPO_ROOT / SCHEMA_PATH
        if not schema_file.is_file():
            print(f"error: schema not found at {schema_file}", file=sys.stderr)
            return 2
        problems = _validate(document, schema_file)
        if problems:
            print(f"error: {len(problems)} schema violation(s):", file=sys.stderr)
            for problem in problems[:20]:
                print(f"  {problem}", file=sys.stderr)
            return 2
        print(f"schema: valid against {SCHEMA_PATH}", file=sys.stderr)

    out_path = Path(args.output)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    gates = document["gates"]
    print(f"wrote {out_path.relative_to(REPO_ROOT)}", file=sys.stderr)
    print(
        f"gates: coverage={gates['coverage']} identity={gates['identity']} "
        f"provenance={gates['provenance']} fidelity={gates['fidelity']} "
        f"overall={gates['overall']}",
        file=sys.stderr,
    )
    if args.json:
        print(json.dumps(document, ensure_ascii=False, indent=2))

    if gates["overall"] != "pass" and not args.allow_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
