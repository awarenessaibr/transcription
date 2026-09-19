#!/usr/bin/env python3
"""Parse ``data/law/**/*.md`` and (re)ingest the law corpus into Qdrant.

Subcommands
-----------
``plan``
    Parse the corpus and print a summary (no network access).
``validate``
    Compare the corpus against a live collection and optionally rewrite
    ``data/law/_mapping/{law_registry.json,LAW_REGISTRY.md}``.
``ingest``
    Write to the repo-owned dense collection (``transcription_law``) by default,
    and optionally refresh the canonical collections (``la8159_law`` +
    ``la8159_law_bm25``) with ``--target canonical`` / ``--target both``.
``search``
    Query the corpus — dense on the local collection, BM25 on the canonical one.
``migrate``
    Reconcile a live collection against the payloads the current writers would
    emit and print a per-point field diff. **Read-only**: there is no write path
    yet (see ``.dev/law_ingest_payload_review.md``).

Examples
--------
    # read-only corpus inventory
    python scripts/ingest_law_corpus.py plan

    # build the repo-owned semantic index
    python scripts/ingest_law_corpus.py ingest

    # what would change in the shared production collection?
    python scripts/ingest_law_corpus.py ingest --target canonical --dry-run

    # refresh the shared payloads + BM25 vectors (dense vectors are preserved)
    python scripts/ingest_law_corpus.py ingest --target canonical

    # coverage + parity report, refreshed registry artifacts
    python scripts/ingest_law_corpus.py validate --write-registry

    # semantic query
    python scripts/ingest_law_corpus.py search "prazo para recurso administrativo" --target local

    # what would schema v1 change on the repo-owned collection? (writes nothing)
    python scripts/ingest_law_corpus.py migrate --target local --dry-run

    # canonical migration diff: per-key counts + 3 sample points
    python scripts/ingest_law_corpus.py migrate --target canonical --dry-run --sample 3
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.infrastructure.qdrant_law_index import (  # noqa: E402
    CANONICAL_BM25_COLLECTION,
    CANONICAL_COLLECTION,
    LOCAL_COLLECTION,
    PAYLOAD_TARGET_CANONICAL,
    PAYLOAD_TARGET_LOCAL,
    QdrantLawIndex,
    _scroll_all,
    build_qdrant_client,
    default_law_dir,
    diff_payloads,
    point_id_for,
    write_registry,
)

logger = logging.getLogger("ingest_law_corpus")


def _load_env() -> None:
    """Load the same .env files as ``src.config`` without importing torch."""
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


def _build_index(args: argparse.Namespace) -> QdrantLawIndex:
    _load_env()
    client = build_qdrant_client(
        args.url or os.getenv("QDRANT_URL"),
        args.api_key or os.getenv("QDRANT_API_KEY"),
    )
    return QdrantLawIndex(
        client=client,
        law_dir=args.law_dir or default_law_dir(),
        canonical_collection=args.collection or CANONICAL_COLLECTION,
        bm25_collection=args.bm25_collection or CANONICAL_BM25_COLLECTION,
        local_collection=args.local_collection or LOCAL_COLLECTION,
        batch_size=args.batch_size,
        preferred_language=args.prefer_language,
        keep_all_languages=args.multi_language,
        keep_separator=args.keep_separator,
    )


def _targets(raw: str) -> list[str]:
    if raw == "both":
        return ["canonical", "local"]
    return [raw]


def _print(obj: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------
def cmd_plan(args: argparse.Namespace) -> int:
    index = _build_index(args)
    plan = index.build_plan()
    summary = plan.as_dict()
    summary["reference_only_details"] = [
        {"file": f.rel_path, "note": f.reference_note} for f in plan.files if f.reference_only
    ]
    summary["skipped_variant_count"] = len(plan.skipped_variants)
    _print(summary, args.json)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    index = _build_index(args)
    plan = index.build_plan()
    report = index.validate(plan, collection=args.collection, compare_payloads=not args.no_payloads)
    payload = {"corpus": plan.as_dict(), "report": report.as_dict()}
    if args.write_registry:
        json_path, md_path = write_registry(plan, report)
        payload["registry"] = {"json": str(json_path), "markdown": str(md_path)}
    _print(payload, args.json)
    return 0 if report.ok else 1


def cmd_ingest(args: argparse.Namespace) -> int:
    index = _build_index(args)
    plan = index.build_plan()
    targets = _targets(args.target)

    canonical = [t for t in targets if t == "canonical"]
    if canonical and not args.dry_run:
        logger.warning(
            "refreshing the SHARED production collection(s) %s + %s: "
            "%d set_payload call(s) (dense vectors preserved) + %d BM25 upsert(s)",
            args.collection or CANONICAL_COLLECTION,
            args.bm25_collection or CANONICAL_BM25_COLLECTION,
            len(plan.by_original_id),
            len(plan.by_original_id),
        )

    if args.dry_run:
        print(
            f"corpus: {len(plan.articles)} article(s), {len(plan.by_original_id)} unique ELI(s), "
            f"{len(plan.reference_only_files)} reference-only file(s), "
            f"{len(plan.collisions)} colliding ELI(s)",
            file=sys.stderr,
        )
        results = index.ingest(
            plan,
            targets=targets,
            dry_run=True,
            allow_new=args.allow_new,
            refresh_payloads=not args.no_refresh_payloads,
            refresh_bm25=not args.no_refresh_bm25,
            recreate_local=args.recreate_local,
            multi_language=args.multi_language,
        )
    else:
        results = index.ingest(
            plan,
            targets=targets,
            dry_run=False,
            allow_new=args.allow_new,
            refresh_payloads=not args.no_refresh_payloads,
            refresh_bm25=not args.no_refresh_bm25,
            recreate_local=args.recreate_local,
            multi_language=args.multi_language,
        )

    payload = {
        "corpus": plan.as_dict(),
        "ingest": {name: stats.as_dict() for name, stats in results.items()},
    }
    _print(payload, args.json)
    failed = sum(stats.failed for stats in results.values())
    return 0 if failed == 0 else 1


def cmd_migrate(args: argparse.Namespace) -> int:
    """Reconcile one collection against the projected payloads. Never writes.

    Phase 1 ships the *report* only: the reviewer needs to see the shape change
    before any of the 1119 production points are touched. ``--dry-run`` is
    therefore the default and ``--no-dry-run`` is refused.
    """
    if not args.dry_run:
        print(
            "migrate: the write path is not implemented (Phase 1 is report-only); "
            "re-run with --dry-run",
            file=sys.stderr,
        )
        return 2

    index = _build_index(args)
    canonical = args.target == "canonical"
    collection = index.canonical.collection if canonical else index.local.collection
    target = PAYLOAD_TARGET_CANONICAL if canonical else PAYLOAD_TARGET_LOCAL

    plan = index.build_plan()

    # Match on ``original_id`` (the ELI), never on a recomputed point ID: the
    # canonical collection's point IDs are split across two UUIDv5 namespaces,
    # so a recomputed ID would look like 285 phantom "would create" points.
    records = _scroll_all(index.client, collection, with_payload=True)
    live: dict[str, dict[str, Any]] = {}
    live_ids: dict[str, str] = {}
    duplicate_elis: list[str] = []
    for record in records:
        payload = dict(record.payload or {})
        eli = str(payload.get("original_id") or payload.get("eli_id") or record.id)
        if eli in live:
            duplicate_elis.append(eli)
            continue
        live[eli] = payload
        live_ids[eli] = str(record.id)

    wanted: dict[str, dict[str, Any]] = {}
    reused_ids = 0
    id_mismatches = 0
    for article in plan.articles:
        computed = point_id_for(article, multi_language=args.multi_language)
        live_id = live_ids.get(article.original_id)
        if live_id is None:
            point_id = computed
        else:
            point_id = live_id
            reused_ids += 1
            if live_id != computed:
                id_mismatches += 1
        wanted[article.original_id] = article.to_payload(point_id, target=target)

    per_key: dict[str, dict[str, int]] = {}
    deltas: list[int] = []
    samples: list[dict[str, Any]] = []
    matched = 0
    for eli, projected in sorted(wanted.items()):
        current = live.get(eli)
        if current is None:
            continue
        matched += 1
        diff = diff_payloads(current, projected)
        deltas.append(diff.byte_delta)
        for bucket, keys in (("added", diff.added), ("removed", diff.removed), ("changed", diff.changed)):
            for key in keys:
                per_key.setdefault(key, {"added": 0, "removed": 0, "changed": 0})[bucket] += 1
        if args.sample and len(samples) < args.sample:
            samples.append(
                {
                    "point_id": live_ids.get(eli),
                    "original_id": eli,
                    "source_file": projected.get("source_file"),
                    "diff": diff.as_dict(),
                }
            )

    missing = sorted(set(wanted) - set(live))
    orphan = sorted(set(live) - set(wanted))
    report: dict[str, Any] = {
        "collection": collection,
        "target": target,
        "corpus_articles": len(plan.articles),
        "live_points": len(records),
        "live_distinct_elis": len(live),
        "duplicate_eli_points": len(duplicate_elis),
        "matched": matched,
        "would_create": len(missing),
        "orphan_in_collection": len(orphan),
        "point_ids_reused": reused_ids,
        "point_ids_differ_from_recipe": id_mismatches,
        "mean_byte_delta": round(sum(deltas) / len(deltas), 1) if deltas else 0.0,
        "min_byte_delta": min(deltas) if deltas else 0,
        "max_byte_delta": max(deltas) if deltas else 0,
        "fields": {key: counts for key, counts in sorted(per_key.items())},
        "samples": samples,
    }
    if args.show_ids:
        report["would_create_elis"] = missing[: args.sample or 20]
        report["orphan_elis"] = orphan[: args.sample or 20]
        report["duplicate_eli_ids"] = duplicate_elis[: args.sample or 20]

    if args.json:
        _print(report, True)
        return 0

    print(f"collection   : {collection}  (target={target})")
    print(f"corpus       : {len(plan.articles)} article(s)")
    print(f"live         : {len(records)} point(s), {len(live)} distinct ELI(s)")
    if duplicate_elis:
        print(f"duplicates   : {len(duplicate_elis)} point(s) share an ELI with another point")
    print(f"matched      : {matched}")
    print(f"would create : {len(missing)}")
    print(f"orphan       : {len(orphan)}  (in the collection, absent from the corpus — left untouched)")
    print(f"ids reused   : {reused_ids}")
    if id_mismatches:
        print(
            f"             : {id_mismatches} live point id(s) differ from stable_point_id(eli) — "
            "expected for canonical (two UUIDv5 namespaces); the live id is reused as-is"
        )
    if deltas:
        print(
            f"byte delta   : mean {sum(deltas) / len(deltas):+.1f}  "
            f"min {min(deltas):+d}  max {max(deltas):+d}  (compact JSON, per point)"
        )
    print()
    print(f"{'field':<22}{'added':>7}{'removed':>9}{'changed':>9}")
    for key, counts in sorted(per_key.items()):
        print(f"{key:<22}{counts['added']:>7}{counts['removed']:>9}{counts['changed']:>9}")
    if not per_key:
        print("(no field differences)")
    for sample in samples:
        diff = sample["diff"]
        print()
        print(f"--- {sample['original_id']}  ({sample['source_file']})")
        print(f"    point_id    {sample['point_id']}")
        print(f"    added       {', '.join(diff['added']) or '—'}")
        print(f"    removed     {', '.join(diff['removed']) or '—'}")
        print(f"    changed     {', '.join(diff['changed']) or '—'}")
        print(f"    byte_delta  {diff['byte_delta']:+d}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    index = _build_index(args)
    hits = index.search(args.query, limit=args.limit, target=args.target, jurisdiction=args.jurisdiction)
    if args.json:
        print(json.dumps([h.as_dict() for h in hits], ensure_ascii=False, indent=2))
        return 0
    if not hits:
        print("no results")
        return 1
    for rank, hit in enumerate(hits, 1):
        snippet = " ".join(hit.content.split())[:220]
        print(f"{rank:>2}. [{hit.score:.3f}] {hit.original_id}  ({hit.source_file}, {hit.language})")
        print(f"    {hit.title}")
        print(f"    {snippet}…")
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def _global_options() -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    """Flags accepted both before and after the subcommand."""
    return [
        (("--law-dir",), {"type": Path, "help": "corpus root (default: <repo>/data/law)"}),
        (("--url",), {"help": "Qdrant URL (default: $QDRANT_URL)"}),
        (("--api-key",), {"help": "Qdrant API key (default: $QDRANT_API_KEY)"}),
        (("--collection",), {"help": f"canonical collection (default: {CANONICAL_COLLECTION})"}),
        (("--bm25-collection",), {"help": f"BM25 collection (default: {CANONICAL_BM25_COLLECTION})"}),
        (("--local-collection",), {"help": f"local collection (default: {LOCAL_COLLECTION})"}),
        (("--batch-size",), {"type": int, "default": 128, "help": "points per upsert batch (default: 128)"}),
        (
            ("--prefer-language",),
            {
                "default": "en",
                "help": "locale kept when the same ELI exists in several languages (default: en)",
            },
        ),
        (
            ("--multi-language",),
            {
                "action": "store_true",
                "help": "keep every language variant instead of one per ELI (language-qualified point IDs)",
            },
        ),
        (
            ("--keep-separator",),
            {
                "action": argparse.BooleanOptionalAction,
                "default": True,
                "help": (
                    "keep the trailing '---' authoring separator in article content "
                    "(default: keep — matches the live collection; use --no-keep-separator "
                    "for cleaner BM25/embedding text)"
                ),
            },
        ),
        (("--json",), {"action": "store_true", "help": "emit machine-readable JSON"}),
        (("-v", "--verbose"), {"action": "store_true", "help": "verbose logging"}),
    ]


def _add_globals(parser: argparse.ArgumentParser, *, suppress_defaults: bool = False) -> None:
    for flags, kwargs in _global_options():
        options = dict(kwargs)
        if suppress_defaults:
            # Let values given *before* the subcommand survive re-parsing.
            options["default"] = argparse.SUPPRESS
        parser.add_argument(*flags, **options)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ingest_law_corpus",
        description="Parse data/law/**/*.md and ingest the law corpus into Qdrant.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    _add_globals(parser)

    shared = argparse.ArgumentParser(add_help=False)
    _add_globals(shared, suppress_defaults=True)

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("plan", parents=[shared], help="parse the corpus and print a summary (no network)")

    p_validate = sub.add_parser("validate", parents=[shared], help="compare corpus against a live collection")
    p_validate.add_argument("--no-payloads", action="store_true", help="skip payload parity comparison")
    p_validate.add_argument("--write-registry", action="store_true", help="refresh _mapping registry artifacts")

    p_ingest = sub.add_parser("ingest", parents=[shared], help="write the corpus to Qdrant")
    p_ingest.add_argument(
        "--target",
        choices=["canonical", "local", "both"],
        default="local",
        help=(
            "local (default) writes only the repo-owned transcription_law collection; "
            "canonical/both also refresh the shared la8159_law + la8159_law_bm25 payloads"
        ),
    )
    p_ingest.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    p_ingest.add_argument(
        "--allow-new",
        action="store_true",
        help=(
            "create articles missing from the canonical collection using deterministic "
            "placeholder dense vectors (la8159_law is a payload store, not a similarity index)"
        ),
    )
    p_ingest.add_argument("--no-refresh-payloads", action="store_true", help="leave existing payloads untouched")
    p_ingest.add_argument("--no-refresh-bm25", action="store_true", help="leave BM25 sparse vectors untouched")
    p_ingest.add_argument("--recreate-local", action="store_true", help="drop and rebuild the local collection")

    p_migrate = sub.add_parser(
        "migrate",
        parents=[shared],
        help="diff a live collection against the projected payloads (read-only)",
    )
    p_migrate.add_argument(
        "--target",
        choices=["local", "canonical"],
        default="local",
        help="collection to reconcile (default: local — the repo-owned transcription_law)",
    )
    p_migrate.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="report only; the write path is not implemented yet (default: on)",
    )
    p_migrate.add_argument("--sample", type=int, default=5, help="per-point diffs to print (default: 5, 0 = none)")
    p_migrate.add_argument(
        "--show-ids",
        action="store_true",
        help="also list the point IDs behind would-create / orphan counts",
    )

    p_search = sub.add_parser("search", parents=[shared], help="query the corpus")
    p_search.add_argument("query")
    p_search.add_argument("--target", choices=["local", "canonical"], default="local")
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--jurisdiction", help="restrict to a jurisdiction code (BR, CL, INT)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    handlers = {
        "plan": cmd_plan,
        "validate": cmd_validate,
        "ingest": cmd_ingest,
        "search": cmd_search,
        "migrate": cmd_migrate,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
