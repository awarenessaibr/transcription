#!/usr/bin/env python3
"""
markdown_law_to_json.py — Scan a corpus of legal markdown files, identify
the layout of each one, and extract every article into structured JSON.

Two-stage design
----------------
1. Scan (default).  Walk every input path, classify each markdown file by
   layout, and print a report grouped by jurisdiction.

2. Extract (--extract).  Parse recognised files and write JSON.  The
   `--emit` flag controls the output shape:

       native   current shape  {metadata, articles: [...]}
       payload  one flat article payload per article, matching the ingestor
                shape (`live` in the API).  Emits norm_type / scope /
                sanctions / direction as separate fields.
       api      full API-response shape for the offline case, matching
                `GET /api/law/article?original_id=...&collection=...`
                with `live=null` and `diff=null` (no Qdrant required).

Jurisdiction convention
-----------------------
Files are expected under <root>/<JURISDICTION>/...  e.g. data/law/CL/x.md.

Usage
-----
    # scan
    python scripts/markdown_law_to_json.py

    # extract as native (back-compat)
    python scripts/markdown_law_to_json.py --extract

    # one flat payload per source file
    python scripts/markdown_law_to_json.py --extract --emit payload

    # one API response per article (matches the live endpoint)
    python scripts/markdown_law_to_json.py --extract --emit api --per-article

    # override framework codes (filename stem -> framework_code)
    python scripts/markdown_law_to_json.py --extract --emit api \\
        --eli-map data/law/_mapping/frameworks.json

The optional --eli-map file is a JSON object mapping source paths to either
a plain framework-code string, or a dict with a "framework_code" key:

    {
      "CL/DGAC_DSO.md":     "DSO",
      "BR/ABEAR_PCD.md":    {"framework_code": "ABEAR_PCD"},
      "BR/L12527_LAI.md":   {"framework_code": "L12527"}
    }
"""

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


# ==========================================================================
# project defaults
# ==========================================================================

DEFAULT_LAW_ROOT = Path("data/law")
DEFAULT_OUT_DIR  = Path("data/law/json")

MARKDOWN_SUFFIXES = {".md", ".markdown"}

#: Mirrors src.infrastructure.qdrant_law_index.EDITABLE_PAYLOAD_FIELDS.
EDITABLE_FIELDS = ["content", "doc_type", "source_file", "tags", "text", "theme", "title"]

DEFAULT_COLLECTION = "transcription_law"


# ==========================================================================
# generic helpers
# ==========================================================================

def strip_md_bold(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", s).strip()


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^\w\s\-]", "_", text, flags=re.UNICODE)
    text = re.sub(r"[\s\-_]+", "_", text).strip("_")
    return (text[:max_len] or "x") or "x"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


META_LINE_RE = re.compile(r"^\s*[-*]\s*\*\*(?P<key>[^*:]+):\*\*\s*(?P<value>.+?)\s*$")


def parse_front_matter(lines):
    meta, in_meta = {}, False
    for raw in lines:
        line = raw.rstrip()
        if re.match(r"^##\s+(Metadata|Metadados)\s*$", line.strip(), re.IGNORECASE):
            in_meta = True
            continue
        if in_meta:
            s = line.strip()
            if s.startswith("---") or s.startswith("#"):
                break
            m = META_LINE_RE.match(line)
            if m:
                meta[m.group("key").strip()] = m.group("value").strip()
    return meta


# ==========================================================================
# layout detection  (unchanged)
# ==========================================================================

RE_A_HEADING = re.compile(r"^###\s+Art\.?\s+\S+\s*[—–-]\s*\S", re.M)
RE_A_FIELD = re.compile(
    r"^\s*\*\*(?:Theme|Themes|Tema|Temas|ELI ID|ID ELI|Tags|Etiquetas)\s*:\*\*",
    re.M | re.I,
)

RE_B_MARKER = re.compile(
    r"^\*\*[ \t]*[^*\n]*?\b(?:ART[IÍ]CULO|ART)\b[^*\n]*?\*\*", re.M,
)
RE_B_LIBRO  = re.compile(r"^#\s+(?:LIBRO|LIVRO|BOOK)\b", re.M | re.I)
RE_B_TITULO = re.compile(r"^##\s+(?:T[IÍ]TULO|TITLE)\b", re.M | re.I)

RE_D_HASH_ARTICLE = re.compile(
    r"^#{1,4}\s+(?:Article|Art\.?|Artículo|Artigo|Section|Rule|Canon|Clause|§)"
    r"\s+\S",
    re.M | re.I,
)

RE_E_NUMBERED_HEADING = re.compile(r"^#{1,4}\s+\d+(?:\.\d+)*[\.\)]?\s+\S", re.M)

RE_F_DASH_SECTION = re.compile(
    r"^#{1,4}\s+"
    r"(?:(?:Seção|Secao|Section|Item|Princípio|Principio|Principle|"
    r"Chapter|Capítulo|Capitulo|Part|Parte)\s+[A-Z0-9]+(?:\s*,\s*)?)?"
    r"(?:[IVXLC]{1,6}(?:\.\d{1,3})*|\d{1,3}(?:\.\d{1,3})*)"
    r"\s*[—–]\s*\S",
    re.M,
)

RE_GENERIC_HEAD = re.compile(r"^#{1,6}\s+\S", re.M)

LAYOUT_DESCRIPTIONS = {
    "structured_heading": '### Art. N — Title  +  **Theme:** / **ELI ID:** / **Tags:**',
    "narrative_code":     '**ART. N.** markers inside  # LIBRO / ## TÍTULO / #### §',
    "hash_article":       '# Article N / # Art. N / # Artículo N / # Section N',
    "dash_section":       '### I — Title / ### Item 3 — Title / ### Seção A, I — Title',
    "numbered_heading":   '## 1. Title, ### 2.1 Title, … (codes of conduct)',
    "whole_file":         'whole document captured as a single article (opt-in)',
    "unknown":            'no known layout matched',
}

KNOWN_LAYOUTS = (
    "structured_heading", "narrative_code", "hash_article",
    "dash_section", "numbered_heading",
)
PARSABLE_LAYOUTS = set(KNOWN_LAYOUTS)
MIN_HITS_FOR_LOOSE = 3


def heading_sample(text: str, n: int = 6):
    out = []
    for m in re.finditer(r"^#{1,6}\s+.*$", text, re.M):
        out.append(m.group(0).rstrip())
        if len(out) >= n:
            break
    return out


def detect_layout(text: str):
    ev = {
        "A.headings":        len(RE_A_HEADING.findall(text)),
        "A.meta_fields":     len(RE_A_FIELD.findall(text)),
        "B.markers":         len(RE_B_MARKER.findall(text)),
        "B.libro":           len(RE_B_LIBRO.findall(text)),
        "B.titulo":          len(RE_B_TITULO.findall(text)),
        "D.hash_article":    len(RE_D_HASH_ARTICLE.findall(text)),
        "E.numbered":        len(RE_E_NUMBERED_HEADING.findall(text)),
        "F.dash_section":    len(RE_F_DASH_SECTION.findall(text)),
        "generic.headings":  len(RE_GENERIC_HEAD.findall(text)),
    }
    if ev["A.headings"] > 0 and ev["A.meta_fields"] > 0:
        return "structured_heading", ev
    if ev["B.markers"] >= 2:
        return "narrative_code", ev
    if ev["D.hash_article"] >= MIN_HITS_FOR_LOOSE:
        return "hash_article", ev
    if ev["F.dash_section"] >= MIN_HITS_FOR_LOOSE:
        return "dash_section", ev
    if ev["E.numbered"] >= MIN_HITS_FOR_LOOSE:
        return "numbered_heading", ev
    if ev["A.headings"] > 0:
        ev["guess"] = "structured_heading without metadata fields"
        return "structured_heading", ev
    if ev["B.markers"] > 0:
        ev["guess"] = "narrative_code with very few ART. markers"
        return "narrative_code", ev
    if ev["D.hash_article"] > 0:
        ev["guess"] = "only a few '# Article N'-style headings"
        return "hash_article", ev
    if ev["F.dash_section"] > 0:
        ev["guess"] = "only a few '### N — Title' dash-separated headings"
        return "dash_section", ev
    if ev["E.numbered"] > 0:
        ev["guess"] = "only a few numbered headings"
        return "numbered_heading", ev
    if ev["generic.headings"] > 0:
        ev["guess"] = "has headings but no recognised article markers"
    else:
        ev["guess"] = "no headings found — plain text or unsupported format"
    return "unknown", ev


# ==========================================================================
# Format A parser — "### Art. N — Title"
# ==========================================================================

ART_HEADING_RE = re.compile(
    r"^###\s+(?P<full_heading>.+?)\s*$"
)
ART_HEADING_PARTS = re.compile(
    r"^Art\.?\s+(?P<num>[^\s—–-]+)\s*[—–-]\s*(?P<title>.*)$",
    re.I,
)

FIELD_RE = re.compile(
    r"^\s*\*\*(?P<key>Themes?|Temas?|ELI ID|ID ELI|Tags|Etiquetas)"
    r"\s*:\*\*\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)

FIELD_KEY_MAP = {
    "theme": "theme", "themes": "theme", "tema": "theme", "temas": "theme",
    "eli id": "eli_id", "id eli": "eli_id",
    "tags": "tags", "etiquetas": "tags",
}


def parse_tags(value: str):
    parts = re.split(r"\s*[·•]\s*", value)
    out = {}
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if ":" in p:
            k, v = p.split(":", 1)
            out[k.strip()] = v.strip()
        else:
            out[p] = True
    return out


def _clean_field_value(v: str) -> str:
    return v.strip().strip("`").strip()


def parse_format_a(text: str):
    lines = text.splitlines()
    meta = parse_front_matter(lines)
    articles, current, seen_body = [], None, False

    def flush():
        nonlocal current, seen_body
        if current is not None:
            current["content"] = "\n".join(current.pop("_content")).strip()
            articles.append(current)
        current, seen_body = None, False

    for line in lines:
        m = ART_HEADING_RE.match(line)
        if m:
            flush()
            full = m.group("full_heading").strip()
            pm = ART_HEADING_PARTS.match(full)
            if pm:
                num   = pm.group("num").strip()
                title = pm.group("title").strip()
            else:
                num, title = full, ""
            current = {
                "article_id":   num,
                "title":        title,
                "full_heading": full,
                "theme":        None,
                "eli_id":       None,
                "tags":         {},
                "hierarchy":    [],
                "_content":     [],
            }
            continue

        if current is None:
            continue
        if re.match(r"^#{1,2}\s", line):
            flush()
            continue
        if line.strip() == "---":
            continue

        if not seen_body:
            fm = FIELD_RE.match(line)
            if fm:
                key = FIELD_KEY_MAP.get(fm.group("key").strip().lower(),
                                        fm.group("key").strip().lower())
                val = _clean_field_value(fm.group("value"))
                if key == "tags":
                    current["tags"] = parse_tags(val)
                else:
                    current[key] = val
                continue
            if line.strip() == "":
                continue
            seen_body = True

        current["_content"].append(line)

    flush()
    return meta, articles


# ==========================================================================
# Format B parser — inline **ART. N.** markers
# ==========================================================================

ARTICLE_MARKER_RE = re.compile(
    r"^\*\*[ \t]*(?P<label>[^*\n]*?\b(?:ART[IÍ]CULO|ART)\b[^*\n]*?)\*\*"
    r"(?P<rest>[^\n]*)$",
    re.IGNORECASE,
)

HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*$")

DESIGNATION_PARSE_RE = re.compile(
    r"^(?:ART[IÍ]CULO|ART)\.?\s+(?P<designation>.+?)\s*$",
    re.IGNORECASE,
)

_MARKER_INLINE_RE = re.compile(
    r"(\*\*[ \t]*(?:ART[IÍ]CULO|ART)\b[^*\n]*?\*\*)",
    re.IGNORECASE,
)


def _normalize_article_markers(text: str) -> str:
    text = _MARKER_INLINE_RE.sub(r"\n\1", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def parse_format_b(text: str):
    text = _normalize_article_markers(text)
    lines = text.splitlines()
    meta = parse_front_matter(lines)
    articles, heading_stack, current = [], [], None

    def flush():
        nonlocal current
        if current is not None:
            current["content"] = "\n".join(current.pop("_content")).strip()
            articles.append(current)
        current = None

    for raw in lines:
        line = raw.rstrip()
        if line.strip() == "---":
            continue

        m = ARTICLE_MARKER_RE.match(line)
        if m:
            flush()
            label = m.group("label").strip()
            label = re.sub(r"\\?\.\s*$", "", label).strip()
            dm = DESIGNATION_PARSE_RE.match(label)
            designation = dm.group("designation").strip() if dm else label
            current = {
                "article_id":   designation,
                "title":        None,
                "full_heading": label,
                "theme":        None,
                "eli_id":       None,
                "tags":         {},
                "hierarchy":    [{"level": lvl, "text": t}
                                 for lvl, t in heading_stack],
                "_content":     [],
            }
            rest = m.group("rest").strip()
            if rest:
                current["_content"].append(rest)
            continue

        hm = HEADING_RE.match(line)
        if hm:
            flush()
            level = len(hm.group("hashes"))
            text_h = strip_md_bold(hm.group("text").strip())
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text_h))
            continue

        if current is not None:
            current["_content"].append(line)

    flush()
    return meta, articles


# ==========================================================================
# Heading-based parsers
# ==========================================================================

HASH_ARTICLE_HEADING_RE = re.compile(
    r"^(?P<hashes>#{1,4})\s+"
    r"(?:Article|Art\.?|Artículo|Artigo|Section|Rule|Canon|Clause|§)\s+"
    r"(?P<num>[^\s\.\:—–\-]+(?:[\.\-][0-9A-Za-z]+)*(?:\s*(?:bis|ter|quáter|quinquies))?)"
    r"[\s\.\:\-—–]*(?P<title>.*?)\s*$",
    re.IGNORECASE,
)

DASH_SECTION_HEADING_RE = re.compile(
    r"^(?P<hashes>#{1,4})\s+"
    r"(?P<designation>"
    r"(?:(?:Seção|Secao|Section|Item|Princípio|Principio|Principle|"
    r"Chapter|Capítulo|Capitulo|Part|Parte)\s+[A-Z0-9]+(?:\s*,\s*)?)?"
    r"(?:[IVXLC]{1,6}(?:\.\d{1,3})*|\d{1,3}(?:\.\d{1,3})*)"
    r")"
    r"\s*[—–]\s*"
    r"(?P<title>.+?)\s*$",
    re.M,
)

NUMBERED_HEADING_RE = re.compile(
    r"^(?P<hashes>#{1,4})\s+"
    r"(?P<num>\d+(?:\.\d+)*)[\.\)]?\s+"
    r"(?P<title>\S.*?)\s*$",
)

ANY_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+?)\s*$")


def parse_heading_articles(text, article_heading_re):
    lines = text.splitlines()
    meta = parse_front_matter(lines)
    articles, heading_stack, current = [], [], None

    def flush():
        nonlocal current
        if current is not None:
            current["content"] = "\n".join(current.pop("_content")).strip()
            articles.append(current)
        current = None

    for raw in lines:
        line = raw.rstrip()
        if line.strip() == "---":
            continue

        m = article_heading_re.match(line)
        if m:
            flush()
            if "designation" in m.groupdict() and m.group("designation"):
                designation = m.group("designation").strip()
            else:
                designation = m.group("num").strip()
            designation = re.sub(r"[\.\:\-—–]+$", "", designation).strip()
            title = (m.groupdict().get("title") or "").strip() or None
            current = {
                "article_id":   designation,
                "title":        title,
                "full_heading": line.lstrip("#").strip(),
                "theme":        None,
                "eli_id":       None,
                "tags":         {},
                "hierarchy":    [{"level": lvl, "text": t}
                                 for lvl, t in heading_stack],
                "_content":     [],
            }
            continue

        hm = ANY_HEADING_RE.match(line)
        if hm:
            flush()
            level = len(hm.group("hashes"))
            text_h = strip_md_bold(hm.group("text").strip())
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text_h))
            continue

        if current is not None:
            current["_content"].append(line)

    flush()
    return meta, articles


# ==========================================================================
# whole-file pseudo-parser
# ==========================================================================

def parse_whole_file(text: str, fallback_id: str = "FULL"):
    meta = parse_front_matter(text.splitlines())
    title = None
    for line in text.splitlines():
        m = re.match(r"^#\s+(.+?)\s*$", line)
        if m:
            title = strip_md_bold(m.group(1))
            break
    article = {
        "article_id":   fallback_id,
        "title":        title,
        "full_heading": title or fallback_id,
        "theme":        None,
        "eli_id":       None,
        "tags":         {},
        "hierarchy":    [],
        "content":      text.strip(),
    }
    return meta, [article]


# ==========================================================================
# parse dispatcher
# ==========================================================================

def parse_file(text: str, layout: str):
    if layout == "structured_heading":
        return parse_format_a(text)
    if layout == "narrative_code":
        return parse_format_b(text)
    if layout == "hash_article":
        return parse_heading_articles(text, HASH_ARTICLE_HEADING_RE)
    if layout == "dash_section":
        return parse_heading_articles(text, DASH_SECTION_HEADING_RE)
    if layout == "numbered_heading":
        return parse_heading_articles(text, NUMBERED_HEADING_RE)
    raise ValueError(f"no parser implemented for layout {layout!r}")


# ==========================================================================
# file collection + jurisdiction
# ==========================================================================

def collect_markdown_files(inputs, excludes=()):
    files, seen = [], set()
    for raw in inputs:
        p = Path(raw)
        if p.is_file():
            if p.suffix.lower() in MARKDOWN_SUFFIXES:
                files.append(p)
            else:
                print(f"[skip] not markdown: {p}", file=sys.stderr)
        elif p.is_dir():
            for sub in p.rglob("*"):
                if sub.is_file() and sub.suffix.lower() in MARKDOWN_SUFFIXES:
                    files.append(sub)
        else:
            print(f"[skip] not found: {p}", file=sys.stderr)

    out = []
    for f in sorted(files, key=lambda x: str(x)):
        rp = f.resolve()
        if rp in seen:
            continue
        if any(substr in str(f) for substr in excludes):
            print(f"[excl] {f}", file=sys.stderr)
            continue
        seen.add(rp)
        out.append(f)
    return out


def jurisdiction_for(path: Path, roots) -> str:
    rp = path.resolve()
    for root in roots:
        try:
            rel = rp.relative_to(Path(root).resolve())
        except ValueError:
            continue
        if len(rel.parts) >= 2:
            return rel.parts[0].upper()
    parent = rp.parent.name
    return parent.upper() if parent else "_unsorted"


def relative_source_path(path: Path, roots) -> str:
    """Path relative to the first matching root, POSIX-style."""
    rp = path.resolve()
    for root in roots:
        try:
            rel = rp.relative_to(Path(root).resolve())
            return rel.as_posix()
        except ValueError:
            continue
    return rp.name


# ==========================================================================
# scan  (unchanged)
# ==========================================================================

def scan(files, roots):
    records, counts, jur_counts = [], {}, {}
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            jur = jurisdiction_for(f, roots)
            records.append({
                "path": str(f), "jurisdiction": jur, "layout": "unknown",
                "evidence": {"error": str(e)}, "heading_sample": [],
            })
            counts["unknown"] = counts.get("unknown", 0) + 1
            jur_counts.setdefault(jur, {})
            jur_counts[jur]["unknown"] = jur_counts[jur].get("unknown", 0) + 1
            continue

        layout, ev = detect_layout(text)
        jur = jurisdiction_for(f, roots)
        records.append({
            "path": str(f), "jurisdiction": jur, "layout": layout,
            "evidence": ev, "heading_sample": heading_sample(text),
        })
        counts[layout] = counts.get(layout, 0) + 1
        jur_counts.setdefault(jur, {})
        jur_counts[jur][layout] = jur_counts[jur].get(layout, 0) + 1

    return {
        "file_count": len(records),
        "roots": [str(r) for r in roots],
        "layout_counts": counts,
        "jurisdiction_counts": jur_counts,
        "files": records,
    }


def print_report(report):
    counts = report["layout_counts"]
    print("\n=== Layout scan ===")
    print(f"Scanned {report['file_count']} markdown file(s) "
          f"under: {', '.join(report['roots'])}\n")

    print("By layout:")
    order = [k for k in KNOWN_LAYOUTS if k in counts]
    order += [k for k in counts if k not in order]
    for layout in order:
        n = counts[layout]
        desc = LAYOUT_DESCRIPTIONS.get(layout, "")
        marker = "   <-- review before extracting" if layout == "unknown" else ""
        print(f"  [ {layout} ]  {n} file(s){marker}")
        if desc:
            print(f"       {desc}")
    print()

    print("By jurisdiction:")
    for jur in sorted(report["jurisdiction_counts"]):
        breakdown = report["jurisdiction_counts"][jur]
        parts = ", ".join(f"{k}={v}" for k, v in sorted(breakdown.items()))
        print(f"  [ {jur:<9} ]  {parts}")
    print()

    unknowns = [r for r in report["files"] if r["layout"] == "unknown"]
    if unknowns:
        print("Files needing review (unknown layout) — with heading samples:")
        for rec in unknowns:
            hint = f"   ({rec['evidence'].get('guess','')})" \
                if "guess" in rec["evidence"] else ""
            n_heads = rec["evidence"].get("generic.headings", 0)
            tag = "  [free-form document?]" if n_heads >= 5 else ""
            print(f"\n  - [{rec['jurisdiction']}] {rec['path']}{hint}{tag}")
            for h in rec["heading_sample"][:6]:
                print(f"        {h}")
        print("\nTip: pass --whole-file-unknown or --exclude <stem>.")
    else:
        print("All files matched a known layout.")


def dump_headings(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    print(f"\n=== Headings in {path} ===\n")
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(r"^#{1,6}\s+\S", line):
            print(f"{i:>5}  {line}")
    print()


# ==========================================================================
# payload construction
# ==========================================================================

_LAW_PREFIX_RE = re.compile(
    r"^(?:L|D|R|DL|DTO|DFL|MC|CF|LC|LEI|DEC|RES)\s*\d+[_\-]",
    re.I,
)


def _derive_framework_code(eli_id, source_path, meta, eli_map):
    # 1. explicit --eli-map
    if eli_map and source_path in eli_map:
        entry = eli_map[source_path]
        if isinstance(entry, dict):
            if "framework_code" in entry:
                return entry["framework_code"]
        elif isinstance(entry, str):
            return entry
    # 2. explicit metadata
    for k in ("Framework", "framework", "framework_code", "Código"):
        if k in meta:
            return str(meta[k]).strip()
    # 3. from ELI: <jur>.<framework>.<rest>
    if eli_id:
        parts = eli_id.split(".")
        if len(parts) >= 3 and parts[0] in {"BR", "CL", "INT", "CORP"}:
            return parts[1]
    # 4. from filename
    stem = Path(source_path).stem
    stripped = _LAW_PREFIX_RE.sub("", stem)
    if stripped != stem:
        return stem[:len(stem) - len(stripped)]  # keep the code prefix
    # last resort
    return stem


def _article_number(article_id: str) -> str:
    return re.sub(
        r"^(?:Art(?:igo|ículo|\.)?|Article|Article|Section|§)\s*",
        "", str(article_id), flags=re.I,
    ).strip()


def _explode_tags(tags) -> dict:
    """Split the tag dict into canonical payload fields."""
    norm_type, scope, sanctions, direction, other = [], [], [], None, []
    if isinstance(tags, dict):
        for k, v in tags.items():
            if isinstance(v, bool):
                other.append(k)
                continue
            vals = [x.strip() for x in re.split(r"[,;|]", str(v)) if x.strip()]
            lk = k.strip().lower()
            if lk == "norm_type":
                norm_type.extend(vals)
            elif lk == "scope":
                scope.extend(vals)
            elif lk == "sanctions":
                sanctions.extend(vals)
            elif lk == "direction":
                direction = vals[0] if vals else None
            else:
                other.extend(f"{k}: {x}" for x in vals)

    tags_list = [f"norm_type: {x}" for x in norm_type]
    tags_list += [f"scope: {x}" for x in scope]
    tags_list += [f"sanctions: {x}" for x in sanctions]
    if direction:
        tags_list.append(f"direction: {direction}")
    tags_list.extend(other)

    return {
        "norm_type":   norm_type,
        "scope":       scope,
        "sanctions":   sanctions,
        "direction":   direction,
        "tags_list":   tags_list,
        "tags_string": " · ".join(tags_list),
    }


def _detect_language(text: str, meta: dict) -> str:
    for k in ("language", "Language", "lang", "Lang", "Idioma", "idioma"):
        if k in meta:
            v = str(meta[k]).strip().lower()
            if v:
                return v[:2]
    t = text.lower()
    scores = {
        "pt": len(re.findall(r"\b(?:que|não|para|como|deve|ser|uma|são|artigo)\b", t)),
        "es": len(re.findall(r"\b(?:que|no|para|como|debe|ser|con|una|son|artículo)\b", t)),
        "en": len(re.findall(r"\b(?:the|and|that|shall|with|for|this|article)\b", t)),
    }
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] > 0 else "unknown"


def _fallback_eli(jurisdiction: str, framework_code: str, article_number: str) -> str:
    if article_number:
        return f"{jurisdiction}.{framework_code}.Art.{article_number}"
    return f"{jurisdiction}.{framework_code}"


def build_context(*, source_path, source_text, jurisdiction,
                  eli_map, ingested_at) -> dict:
    return {
        "source_path":     source_path,
        "source_file":     Path(source_path).name,
        "source_sha256":   _sha256(source_text),
        "sha256_short":    _sha256(source_text)[:16],
        "jurisdiction":    jurisdiction,
        "ingested_at":     ingested_at,
        "eli_map":         eli_map or {},
    }


def build_payload(article: dict, ctx: dict) -> dict:
    """Flat payload in the same shape the ingestor writes to Qdrant (`live`)."""
    exploded     = _explode_tags(article.get("tags"))
    article_id   = str(article.get("article_id") or "")
    number       = _article_number(article_id)
    framework    = _derive_framework_code(article.get("eli_id"),
                                          ctx["source_path"],
                                          {}, ctx["eli_map"])
    eli_id       = article.get("eli_id") or _fallback_eli(
        ctx["jurisdiction"], framework, number)
    full_title   = article.get("full_heading") or article.get("title") or ""
    content      = article.get("content") or ""
    language     = _detect_language(content, {})
    doc_type     = "unknown"

    return {
        "id":             "",
        "eli_id":         eli_id,
        "original_id":    eli_id,
        "article_number": number,
        "framework_code": framework,
        "jurisdiction":   ctx["jurisdiction"],
        "title":          full_title,
        "theme":          article.get("theme") or "",
        "norm_type":      exploded["norm_type"],
        "scope":          exploded["scope"],
        "direction":      exploded["direction"],
        "sanctions":      exploded["sanctions"],
        "tags":           exploded["tags_list"],
        "content":        content,
        "text":           content,
        "source_file":    ctx["source_file"],
        "source_path":    ctx["source_path"],
        "source_sha256":  ctx["source_sha256"],
        "language":       language,
        "doc_type":       doc_type,
        "record_kind":    "article",
        "reference_only": False,
        "data_type":      "law",
        "schema_version": "1",
        "ingested_at":    ctx["ingested_at"],
        "updated_at":     ctx["ingested_at"],
    }


def build_expected(payload: dict, ctx: dict) -> dict:
    """The shape the API returns as `expected` — recomputed from the corpus."""
    tag_string = " · ".join(payload["tags"])
    return {
        "original_id":    payload["original_id"],
        "eli_id":         payload["eli_id"],
        "title":          payload["title"],
        "text":           payload["text"],
        "content":        payload["content"],
        "theme":          payload["theme"],
        "tags":           tag_string,
        "source_file":    payload["source_file"],
        "doc_type":       payload["doc_type"],
        "article_number": payload["article_number"],
        "record_kind":    payload["record_kind"],
        "schema_version": payload["schema_version"],
        "original_data": {
            "id":          payload["id"],
            "title":       payload["title"],
            "source_file": payload["source_file"],
            "theme":       payload["theme"],
            "tags":        tag_string,
            "content":     payload["content"],
            "original_id": payload["original_id"],
        },
        "metadata": {
            "data_type":      payload["data_type"],
            "doc_type":       payload["doc_type"],
            "ingestion_time": ctx["ingested_at"],
        },
        "framework_code": payload["framework_code"],
        "jurisdiction":   payload["jurisdiction"],
        "language":       payload["language"],
        "sha256_short":   ctx["sha256_short"],
        "source_path":    payload["source_path"],
    }


def build_corpus(payload: dict, ctx: dict) -> dict:
    return {
        "title":          payload["title"],
        "theme":          payload["theme"],
        "tags":           " · ".join(payload["tags"]),
        "content":        payload["content"],
        "source_file":    payload["source_file"],
        "source_path":    payload["source_path"],
        "doc_type":       payload["doc_type"],
        "language":       payload["language"],
        "jurisdiction":   payload["jurisdiction"],
        "framework_code": payload["framework_code"],
        "sha256_short":   ctx["sha256_short"],
    }


def build_api_response(payload: dict, ctx: dict,
                       collection: str = DEFAULT_COLLECTION) -> dict:
    """Offline equivalent of GET /api/law/article?original_id=..."""
    return {
        "original_id":     payload["original_id"],
        "collection":      collection,
        "indexed":         False,   # offline: we don't know if it's in Qdrant
        "point_id":        "",
        "live":            None,
        "expected":        build_expected(payload, ctx),
        "editable_fields": EDITABLE_FIELDS,
        "corpus":          build_corpus(payload, ctx),
        "diff":            None,
    }


# ==========================================================================
# extraction
# ==========================================================================

def safe_filename(article_id: str, index: int) -> str:
    return f"{index:04d}_{slugify(article_id)}.json"


def output_dir_for(base: Path, jurisdiction: str, flat: bool) -> Path:
    return base if flat else base / jurisdiction


def extract_file(path: Path, layout: str, out_dir: Path, per_article: bool,
                 jurisdiction: str, source_path: str,
                 emit: str, eli_map: dict, ingested_at: str,
                 collection: str = DEFAULT_COLLECTION,
                 force_whole_file: bool = False) -> int:
    text = path.read_text(encoding="utf-8")

    if force_whole_file:
        meta, articles = parse_whole_file(text, fallback_id=path.stem.upper())
        effective_layout = "whole_file"
    else:
        meta, articles = parse_file(text, layout)
        effective_layout = layout

    ctx = build_context(
        source_path=source_path,
        source_text=text,
        jurisdiction=jurisdiction,
        eli_map=eli_map,
        ingested_at=ingested_at,
    )

    payloads = [build_payload(a, ctx) for a in articles]

    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- bundle (per source file) ----------------------------------------
    if emit == "native":
        bundle = {
            "source_file":   path.name,
            "source_path":   source_path,
            "jurisdiction":  jurisdiction,
            "format":        effective_layout,
            "metadata":      meta,
            "article_count": len(articles),
            "articles":      articles,
        }
    elif emit == "payload":
        bundle = {
            "source_file":   path.name,
            "source_path":   source_path,
            "jurisdiction":  jurisdiction,
            "format":        effective_layout,
            "metadata":      meta,
            "article_count": len(payloads),
            "payloads":      payloads,
        }
    elif emit == "api":
        bundle = {
            "source_file":   path.name,
            "source_path":   source_path,
            "jurisdiction":  jurisdiction,
            "format":        effective_layout,
            "metadata":      meta,
            "article_count": len(payloads),
            "responses":     [
                build_api_response(p, ctx, collection=collection)
                for p in payloads
            ],
        }
    else:
        raise ValueError(f"unknown --emit value: {emit!r}")

    (out_dir / f"{path.stem}.articles.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- per-article -----------------------------------------------------
    if per_article:
        subdir = out_dir / path.stem
        subdir.mkdir(parents=True, exist_ok=True)
        for i, payload in enumerate(payloads):
            fname = safe_filename(str(payload.get("article_number")
                                      or payload.get("original_id") or "art"), i)
            if emit == "native":
                body = articles[i]
            elif emit == "payload":
                body = payload
            elif emit == "api":
                body = build_api_response(payload, ctx, collection=collection)
            else:
                raise ValueError(f"unknown --emit value: {emit!r}")
            (subdir / fname).write_text(
                json.dumps(body, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    return len(payloads)


# ==========================================================================
# main
# ==========================================================================

def main():
    ap = argparse.ArgumentParser(
        description="Scan and (optionally) extract legal markdown files.",
    )
    ap.add_argument("inputs", nargs="*", type=Path,
                    help=f"Files or directories to scan (recursively). "
                         f"Defaults to {DEFAULT_LAW_ROOT}.")
    ap.add_argument("--extract", action="store_true",
                    help="After scanning, extract articles and write JSON.")
    ap.add_argument("-o", "--output-dir", type=Path, default=DEFAULT_OUT_DIR,
                    help=f"Where to write extracted JSON "
                         f"(default: {DEFAULT_OUT_DIR}).")
    ap.add_argument("--flat", action="store_true",
                    help="Do not split output by jurisdiction.")
    ap.add_argument("--per-article", action="store_true",
                    help="Also write one JSON file per article.")
    ap.add_argument("--emit", choices=("native", "payload", "api"),
                    default="native",
                    help="Output shape: native (default), flat payload, "
                         "or full API response.")
    ap.add_argument("--collection", default=DEFAULT_COLLECTION,
                    help=f"Collection name embedded in `api` output "
                         f"(default: {DEFAULT_COLLECTION}).")
    ap.add_argument("--eli-map", type=Path, default=None,
                    help="Optional JSON mapping source_path -> framework_code "
                         "(or {framework_code: ...}).")
    ap.add_argument("--ingestion-time", default=None,
                    help="Override ingestion timestamp (ISO 8601). "
                         "Useful for reproducible builds.")
    ap.add_argument("--report", type=Path, default=None,
                    help="Write the scan report as JSON to this path.")
    ap.add_argument("--exclude", action="append", default=[],
                    metavar="SUBSTR",
                    help="Skip files whose path contains SUBSTR (repeatable).")
    ap.add_argument("--whole-file-unknown", action="store_true",
                    help="Extract unknown-layout files as a single article.")
    ap.add_argument("--whole-file", action="append", default=[],
                    metavar="SUBSTR",
                    help="Force whole-file treatment for paths containing "
                         "SUBSTR (repeatable).")
    ap.add_argument("--dump-headings", type=Path, default=None,
                    help="Print every heading in the given file and exit.")
    args = ap.parse_args()

    if args.dump_headings:
        dump_headings(args.dump_headings)
        return

    # ---- inputs ------------------------------------------------------------
    if args.inputs:
        inputs = args.inputs
    elif DEFAULT_LAW_ROOT.is_dir():
        inputs = [DEFAULT_LAW_ROOT]
        print(f"[auto] no inputs given; scanning {DEFAULT_LAW_ROOT}/")
    else:
        ap.error(f"no inputs given and default '{DEFAULT_LAW_ROOT}' "
                 f"does not exist")

    # ---- ELI map -----------------------------------------------------------
    eli_map = {}
    if args.eli_map:
        try:
            eli_map = json.loads(args.eli_map.read_text(encoding="utf-8"))
        except Exception as e:                       # noqa: BLE001
            print(f"[err ] could not read --eli-map {args.eli_map}: {e}",
                  file=sys.stderr)
            sys.exit(2)

    ingested_at = args.ingestion_time or _iso_now()

    # ---- collect + scan ----------------------------------------------------
    files = collect_markdown_files(inputs, excludes=args.exclude)
    if not files:
        print("No markdown files found.", file=sys.stderr)
        sys.exit(1)

    report = scan(files, inputs)
    print_report(report)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nScan report written to {args.report}")

    # ---- extraction --------------------------------------------------------
    if not args.extract:
        print("\nExtraction skipped (pass --extract to write JSON files).")
        return

    forced_whole = set()
    if args.whole_file:
        for rec in report["files"]:
            if any(s in rec["path"] for s in args.whole_file):
                forced_whole.add(rec["path"])

    unknown_extracted, unknown_skipped = [], []
    for rec in report["files"]:
        if rec["layout"] != "unknown":
            continue
        if args.whole_file_unknown or rec["path"] in forced_whole:
            unknown_extracted.append(rec)
        else:
            unknown_skipped.append(rec)

    if unknown_extracted:
        print(f"\n-- whole-file capture enabled for "
              f"{len(unknown_extracted)} unknown-layout file(s):")
        for rec in unknown_extracted:
            print(f"     [{rec['jurisdiction']}] {rec['path']}")
    if unknown_skipped:
        print(f"\n!! {len(unknown_skipped)} file(s) use an unknown layout "
              f"and will be skipped during extraction:")
        for rec in unknown_skipped:
            print(f"     [{rec['jurisdiction']}] {rec['path']}")

    print(f"\n=== Extraction ===\n"
          f"emit={args.emit}  output={args.output_dir}/"
          f"{'(flat)' if args.flat else ' (grouped by jurisdiction)'}")

    total, per_jur = 0, {}
    for rec in report["files"]:
        layout = rec["layout"]
        path   = Path(rec["path"])
        jur    = rec["jurisdiction"]

        force_wf = False
        if layout in PARSABLE_LAYOUTS:
            if rec["path"] in forced_whole:
                force_wf = True
        else:
            if rec["path"] in forced_whole or args.whole_file_unknown:
                force_wf = True
            else:
                print(f"[skip] [{jur}] {path.name}: layout={layout!r}")
                continue

        src_path = relative_source_path(path, inputs)
        out_dir = output_dir_for(args.output_dir, jur, args.flat)
        try:
            n = extract_file(path, layout, out_dir,
                             args.per_article, jur, src_path,
                             args.emit, eli_map, ingested_at,
                             collection=args.collection,
                             force_whole_file=force_wf)
        except Exception as e:                       # noqa: BLE001
            print(f"[err ] [{jur}] {path.name}: {e}", file=sys.stderr)
            continue
        total += n
        per_jur[jur] = per_jur.get(jur, 0) + n
        mode = "whole-file" if force_wf else layout
        extra = " (+ per-article files)" if args.per_article else ""
        print(f"[ok  ] [{jur}] {path.name}: {n} articles [{mode}]{extra}")

    print("\n=== Summary ===")
    for jur in sorted(per_jur):
        print(f"  {jur:<9}  {per_jur[jur]} articles")
    print(f"\nDone. {total} articles extracted to {args.output_dir}/")


if __name__ == "__main__":
    main()