Understood — treating this as an external ingestion branch, not the `violation_pack` project. Here's the spec standalone.

---

## Canonical law point payload (schema v1)

```jsonc
{
  // identity
  "eli_id":          "BR.CBA.T3.C1.Art.74",
  "article_number":  "74",
  "framework_code":  "CBA",
  "jurisdiction":    "BR",

  // human-facing
  "title":           "Art. 74 — CBA Title III, Chapter I, Article 74 – Brazilian Aeronautical Registry Procedures",
  "theme":           "Regulatory Compliance",

  // classification
  "norm_type":       "definition",
  "scope":           "contractual",
  "direction":       null,
  "sanctions":       [],
  "tags":            ["norm_type: definition", "scope: contractual"],

  // provenance
  "source_file":     "L7565_CBA.md",
  "source_path":     "data/law/BR/L7565_CBA.md",
  "source_sha256":   "<64 hex chars>",
  "language":        "pt",
  "reference_only":  false,

  // content
  "text":            "Art. 74. No Registro Aeronáutico Brasileiro serão feitas: …",

  // lifecycle
  "doc_type":        "law_article",
  "data_type":       "law",
  "schema_version":  "1",
  "ingested_at":     "2026-09-13T03:23:41.770291Z",
  "updated_at":      "2026-09-13T03:23:41.770291Z"
}
```

---

## Field rules

### Identity

| Field | Rule |
|---|---|
| `eli_id` | The full ELI from the source. Was `original_id`. Renamed because it says what it is. |
| `article_number` | Extracted: `eli_id.rsplit(".Art.", 1)[-1].split(".")[0]`. Needed so a lookup by article number (`"74"`) doesn't have to reverse-engineer the ELI tail. |
| `framework_code` | Second segment of the ELI (`"CBA"`). Already present. |
| `jurisdiction` | First segment of the ELI (`"BR"`). Already present. |
| `id` | **Drop.** Never duplicate the Qdrant point ID into the payload. |

### Classification

The source markdown uses two tag styles. Both must land in the same structured fields.

**Style A** (single line, `·`-separated, used by CHIPENCOD / ABEAR / CBA):
```
**Tags:** norm_type: definition · scope: contractual
```

**Style B** (inline pipe-separated, used by D7724):
```
**Norm type:** procedure | **Direction:** mandatory | **Scope:** administrative
```

**Style C** (no tags at all):
```
(blank)
```

Parser contract:

```python
def parse_article_tags(block: str) -> dict:
    """Return {norm_type, scope, direction, sanctions, tags}.

    tags is the raw list of tokens (for display / debugging).
    The structured fields are what queries filter on.
    Absent values are None; sanctions is always a list.
    """
    out = {"norm_type": None, "scope": None, "direction": None,
           "sanctions": [], "tags": []}

    m = re.search(r"\*\*Tags:\*\*\s*(.+)", block)
    if m:
        for tok in (t.strip() for t in m.group(1).split("·")):
            if not tok: continue
            out["tags"].append(tok)
            if ":" not in tok: continue
            k, _, v = tok.partition(":")
            k, v = k.strip().lower(), v.strip()
            if k in {"norm_type", "scope", "direction"}:
                out[k] = v
            elif k == "sanctions":
                out["sanctions"] = [s.strip() for s in v.split(",") if s.strip()]

    for label, key in [("Norm type", "norm_type"),
                       ("Direction", "direction"),
                       ("Scope", "scope")]:
        m2 = re.search(rf"\*\*{label}:\*\*\s*([^|\n]+)", block)
        if m2:
            out[key] = m2.group(1).strip()

    return out
```

**Rule:** `tags` remains as a list of raw tokens. `norm_type` / `scope` / `direction` / `sanctions` are the filterable fields.

### Provenance

| Field | Rule |
|---|---|
| `source_file` | Basename only. Already correct. |
| `source_path` | **Project-relative** (`data/law/BR/L7565_CBA.md`), not absolute. Absolute paths break when the corpus moves. |
| `source_sha256` | **Full 64 hex.** Was `sha256_short` (16 chars). Short is for display; full is what a cache-drift check compares against. |
| `language` | `pt` / `es` / `en` — one of the three the corpus uses. Already present. |
| `reference_only` | Boolean. `true` for whole-code full-texts and corporate policy files that have no ELI article headers. |

### Content

| Field | Rule |
|---|---|
| `text` | The article body verbatim. Keep. |
| `content` | **Drop.** Byte-identical to `text` in every sample seen. One content field. |

### Lifecycle

| Field | Rule |
|---|---|
| `doc_type` | `"law_article"` for ELI-keyed points, `"law_reference"` for reference-only points. Currently `"unknown"`. |
| `data_type` | `"law"`. Currently nested under `metadata`. Lift to top level. |
| `schema_version` | `"1"`. Lets future shape changes be detected without guessing. |
| `ingested_at` | ISO 8601 UTC. The wall-clock of the write. |
| `updated_at` | ISO 8601 UTC. Equals `ingested_at` on first write; advances on overwrite. |

**Drop the `metadata` wrapper.** Every field in it now lives at the root.

**Drop `original_data`.** It's a complete duplicate of the root fields. Keeping it doubles the payload for zero information.

---

## Point IDs

Two conventions, both deterministic:

```python
import uuid
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")   # DNS namespace

def article_point_id(framework_code: str, article_number: str) -> str:
    return str(uuid.uuid5(_NS, f"article|{framework_code}|{article_number}"))

def reference_point_id(jurisdiction: str, source_file: str) -> str:
    return str(uuid.uuid5(_NS, f"law_reference|{jurisdiction}|{source_file}"))
```

Deterministic → re-ingesting the same source overwrites in place. The current random UUID (`b7de404c-7c40-...`) creates a new point every run.

---

## Reference-only files

Files whose registry entry has `reference_only: true` (whole-code consolidated texts, corporate ethics policies) skip the per-article loop and emit **one** point per file:

```jsonc
{
  "eli_id":          null,
  "article_number":  null,
  "framework_code":  "CC",
  "jurisdiction":    "CL",
  "title":           "Chilean Civil Code and Related Laws — Consolidated Text",
  "theme":           null,
  "norm_type":       null,
  "scope":           null,
  "direction":       null,
  "sanctions":       [],
  "tags":            [],
  "source_file":     "ChileanCivilCodeandRelatedLaws.md",
  "source_path":     "data/law/CL/ChileanCivilCodeandRelatedLaws.md",
  "source_sha256":   "<64 hex>",
  "language":        "es",
  "reference_only":  true,
  "text":            "<full file text, chunked if over embedder limit>",
  "doc_type":        "law_reference",
  "data_type":       "law",
  "schema_version":  "1",
  "ingested_at":     "...",
  "updated_at":      "..."
}
```

Point ID via `reference_point_id(jurisdiction, source_file)`.

**Why this matters:** without the flag, a scanner that globs `data/law/**/*.md` will try to article-parse `ChileanCivilCodeandRelatedLaws.md`, find zero `### Art.` headers, and silently produce zero points. The flag makes that decision explicit and queryable.

---

## Payload indexes

Create these on the collection after creation. They make the filter queries cheap.

| Field | Schema |
|---|---|
| `eli_id` | `keyword` |
| `framework_code` | `keyword` |
| `jurisdiction` | `keyword` |
| `language` | `keyword` |
| `article_number` | `keyword` |
| `norm_type` | `keyword` |
| `scope` | `keyword` |
| `reference_only` | `bool` |
| `source_file` | `keyword` |

No index on `text`, `title`, `theme`, or `tags` — those are for full-text match or human display, not equality filters.

---

## What the shape buys you

**Single identity, single content, single classification.**
Every ELI-keyed point has exactly one `eli_id`, one `text`, one `norm_type`. No wrapper, no duplicate.

**Deterministic re-ingest.**
Same source → same point ID → overwrite, not duplicate.

**Queryable classification.**
`norm_type="penalty"` and `scope="criminal"` are filter predicates, not substring searches over a display string.

**Reference files distinguishable from articles without special-casing.**
`reference_only=true` → exclude from article lookups, include in full-text fallback. One boolean, one filter.

**Full SHA on the payload.**
Cache-drift detection becomes a Qdrant read, not a disk read.

**Schema versioning from day one.**
The current shape already differs from the D2181 sample; the next change is going to happen too. `schema_version` makes it detectable.