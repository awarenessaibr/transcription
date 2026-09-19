# Adding a "Review with LLM" section to the payload viewer

Two drop-in pieces: a new backend endpoint that talks to the LLM, and a UI section inside the existing payload modal that shows the suggestions as a checklist and applies the selected ones via the existing `PATCH /payload` endpoint.

---

## 1. Backend — `POST /api/law/suggest`

Add to `src/api/law_registry_router.py` (or wherever your router lives). It reuses the live payload, the corpus-recomputed payload, and a snippet of the source markdown, then asks the LLM for a minimal set of field updates.

```python
# ---------------------------------------------------------------------------
# LLM-assisted payload review
# ---------------------------------------------------------------------------
from src.infrastructure.qdrant_law_index import (
    EDITABLE_PAYLOAD_FIELDS,
    PayloadEditError,
)
# TODO: point these at whatever LLM client your project already uses.
# The endpoint below only needs a single function:
#     call_llm_json(system: str, user: str) -> dict
# Implement it in src/infrastructure/llm.py (OpenAI, Anthropic, Ollama, …).
from src.infrastructure.llm import call_llm_json


#: Fields the LLM must never touch.
_IMMUTABLE_FIELDS = {
    "id", "eli_id", "original_id", "article_number",
    "source_file", "source_path", "source_sha256", "sha256_short",
    "schema_version", "ingested_at", "updated_at",
    "record_kind", "data_type", "reference_only",
}

#: Fields the reviewer usually wants filled in when empty / unknown.
_DEFAULT_REVIEW_FIELDS = [
    "theme", "norm_type", "scope", "sanctions", "direction",
    "doc_type", "language", "title", "tags",
]


class SuggestRequest(BaseModel):
    """Ask the LLM for a minimal set of payload improvements."""

    original_id: str
    collection: str = CANONICAL_COLLECTION
    fields: list[str] | None = Field(
        None,
        description="Which fields to ask about. Defaults to the fields that "
                    "are empty / 'unknown' in the live payload.",
    )
    include_content: bool = Field(
        False,
        description="Also propose content edits (off by default — higher risk).",
    )
    instructions: str | None = Field(
        None,
        description="Optional extra guidance for the model.",
    )


_SUGGEST_SYSTEM = """\
You review payloads for a legal knowledge base that ingests statutes,
regulations, cases and soft-law instruments from many jurisdictions.

You will be given three JSON blocks:
  - CURRENT:   the payload currently stored in Qdrant
  - EXPECTED:  what the offline ingester would compute from the corpus today
  - SNIPPET:   the source Markdown covering this article (may be truncated)

Return a minimal set of field updates that IMPROVE the payload.

Rules:
  1. Never touch these fields: id, eli_id, original_id, article_number,
     source_file, source_path, source_sha256, sha256_short,
     schema_version, ingested_at, updated_at, record_kind, data_type,
     reference_only.
  2. Only propose a change when you have concrete evidence in SNIPPET
     or EXPECTED. When in doubt, do not propose.
  3. Prefer high-confidence, low-risk edits:
        - fill in empty strings, empty lists, or "unknown" values
        - fix obvious typos or stray escape characters
        - canonicalise enum-like fields (doc_type, norm_type, scope,
          sanctions, direction) to lower_snake_case
  4. Do NOT propose content edits unless the caller explicitly asks.
  5. Every suggestion needs a one-sentence rationale grounded in the input.
  6. confidence is one of "low", "medium", "high".
  7. If nothing should change, return an empty suggestions array.
  8. The field name must match exactly one of the allowed field names.

Respond with strict JSON, no prose, no markdown fences:
{"suggestions": [
  {"field": "...", "current": <any>, "suggested": <any>,
   "rationale": "...", "confidence": "low|medium|high"}
]}
"""


def _review_field_list(live: dict, requested: list[str] | None,
                       include_content: bool) -> list[str]:
    if requested:
        candidates = [f for f in requested if f not in _IMMUTABLE_FIELDS]
    else:
        candidates = list(_DEFAULT_REVIEW_FIELDS)
        # add any empty / "unknown" editable field
        for f in sorted(EDITABLE_PAYLOAD_FIELDS):
            if f in _IMMUTABLE_FIELDS or f == "content":
                continue
            v = live.get(f)
            if v in (None, "", [], {}, "unknown"):
                if f not in candidates:
                    candidates.append(f)
    if include_content and "content" not in candidates:
        candidates.append("content")
    return [f for f in candidates if f not in _IMMUTABLE_FIELDS]


def _snippet_for(index: QdrantLawIndex, article: LawArticle, max_chars: int = 4000) -> str:
    """Best-effort source context for the article."""
    try:
        text = Path(article.source_path).read_text(encoding="utf-8", errors="replace") \
            if Path(article.source_path).is_file() \
            else None
    except OSError:
        text = None
    if text is None:
        try:
            text = index.read_source(article.source_path)  # if your index exposes this
        except Exception:                                   # noqa: BLE001
            text = article.content
    if not text:
        return ""
    # if the content is in the file, give the model the surrounding window
    needle = (article.content or "").strip()[:120]
    if needle and needle in text:
        i = text.index(needle)
        start = max(0, i - max_chars // 4)
        end   = min(len(text), i + max_chars)
        return text[start:end]
    return text[:max_chars]


@router.post("/suggest")
def suggest_payload(request: SuggestRequest) -> dict[str, Any]:
    """Ask the LLM for a minimal set of payload improvements."""
    index = get_index()
    try:
        live = index.get_article(request.original_id, collection=request.collection)
    except Exception as exc:                                # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Qdrant unavailable: {exc}") from exc

    corpus = _corpus_article(index, request.original_id)
    if live is None and corpus is None:
        raise HTTPException(status_code=404, detail=f"Unknown article: {request.original_id}")

    live_view = live or {}
    expected_view = _expected_payload(corpus, live_view.get("id") or "") if corpus else {}
    fields = _review_field_list(live_view, request.fields, request.include_content)

    snippet = _snippet_for(index, corpus) if corpus else ""

    # Trim the views to the fields the model may consider.
    def _slice(d: dict) -> dict:
        out = {k: d[k] for k in fields if k in d}
        # always show the title / framework_code / jurisdiction for context
        for k in ("title", "framework_code", "jurisdiction", "language"):
            if k in d:
                out.setdefault(k, d[k])
        return out

    user_prompt = json.dumps(
        {
            "allowed_fields": fields,
            "CURRENT": _slice(live_view),
            "EXPECTED": _slice(expected_view),
            "SNIPPET": snippet,
            "extra_instructions": request.instructions or "",
        },
        ensure_ascii=False,
        indent=2,
    )

    try:
        result = call_llm_json(_SUGGEST_SYSTEM, user_prompt)
    except Exception as exc:                                # noqa: BLE001
        logger.exception("[law] LLM review failed for %s", request.original_id)
        raise HTTPException(status_code=502, detail=f"LLM error: {exc}") from exc

    raw = (result or {}).get("suggestions") or []

    # Keep only suggestions that touch a reviewable, editable field and differ
    # from the live value.
    allowed = set(fields) & set(EDITABLE_PAYLOAD_FIELDS) - _IMMUTABLE_FIELDS
    clean: list[dict[str, Any]] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        f = s.get("field")
        if f not in allowed:
            continue
        cur = live_view.get(f)
        sug = s.get("suggested")
        if cur == sug:
            continue
        clean.append({
            "field":      f,
            "current":    cur,
            "suggested":  sug,
            "rationale":  str(s.get("rationale") or "").strip(),
            "confidence": str(s.get("confidence") or "medium").lower(),
        })

    return {
        "original_id": request.original_id,
        "collection":  request.collection,
        "fields_reviewed": fields,
        "suggestions": clean,
        "model":       (result or {}).get("_model"),
        "usage":       (result or {}).get("_usage"),
    }
```

And the tiny provider shim (implement once, use everywhere):

```python
# src/infrastructure/llm.py
"""Minimal JSON-in / JSON-out LLM helper.

Wire this to whichever provider your project already uses. The only
contract the router cares about is:
    call_llm_json(system: str, user: str) -> dict
The returned dict is the parsed JSON body of the model's reply, optionally
augmented with `_model` and `_usage` keys for telemetry.
"""
from __future__ import annotations
import json, re
# from openai import OpenAI  # or anthropic, ollama, …

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)

def _parse_json(raw: str) -> dict:
    m = _JSON_FENCE.search(raw)
    if m:
        raw = m.group(1)
    return json.loads(raw)

def call_llm_json(system: str, user: str) -> dict:
    # Replace this body with your provider call. Example:
    #
    #   client = OpenAI()
    #   resp = client.chat.completions.create(
    #       model="gpt-4o-mini",
    #       response_format={"type": "json_object"},
    #       messages=[{"role": "system", "content": system},
    #                 {"role": "user",   "content": user}],
    #   )
    #   data = _parse_json(resp.choices[0].message.content)
    #   data["_model"] = resp.model
    #   data["_usage"] = resp.usage.model_dump() if resp.usage else None
    #   return data
    raise NotImplementedError("wire call_llm_json to your LLM provider")
```

---

## 2. Frontend — a Review section inside the payload modal

Three additions to `templates/law-registry.html`: CSS, one HTML block inside `renderArticleModal`, and the JS handlers.

### 2.1 CSS — paste near the payload-editor styles

```css
/* ---------- LLM payload review ---------- */
.review-panel { margin-top: 8px; }

.review-actions {
  display: flex; align-items: center; gap: 9px; flex-wrap: wrap;
  margin-bottom: 12px;
}
.review-note { font-size: 0.72rem; color: var(--text-muted); line-height: 1.6; }

.review-opt {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: 0.74rem; color: var(--text-secondary);
}
.review-opt input { accent-color: var(--accent); }

.suggest-list { display: grid; gap: 8px; }

.suggest-card {
  border: 1px solid var(--border); border-left: 3px solid var(--accent);
  border-radius: 6px; padding: 11px 13px; background: var(--bg-card);
}
.suggest-card[data-conf="low"]    { border-left-color: var(--status-analysis); }
.suggest-card[data-conf="high"]   { border-left-color: var(--status-note); }
.suggest-card.is-off { opacity: .55; }

.suggest-head {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-bottom: 8px;
}
.suggest-head .field {
  font-family: var(--mono); font-size: 0.7rem; color: var(--text-primary);
  background: var(--bg-surface); padding: 3px 8px; border-radius: 2px;
}
.suggest-head .conf {
  font-family: var(--mono); font-size: 0.6rem; text-transform: uppercase;
  letter-spacing: .07em; padding: 2px 6px; border-radius: 999px;
  border: 1px solid currentColor;
}
.suggest-head .conf.high   { color: var(--status-note); }
.suggest-head .conf.medium { color: var(--accent); }
.suggest-head .conf.low    { color: var(--status-analysis); }
.suggest-head .spacer { flex: 1; }

.suggest-diff {
  display: grid; grid-template-columns: 1fr 1fr; gap: 8px;
  font-family: var(--mono); font-size: 0.7rem; line-height: 1.55;
}
.suggest-diff > div { padding: 8px 10px; border-radius: 4px; overflow-x: auto; }
.suggest-diff .before { background: var(--status-flag-dim); color: var(--status-flag); }
.suggest-diff .after  { background: var(--status-note-dim); color: var(--status-note); }
.suggest-diff .col    { display: block; opacity: .7; margin-bottom: 4px; font-size: 0.58rem; letter-spacing: .08em; text-transform: uppercase; }
.suggest-rationale {
  margin-top: 8px; font-size: 0.74rem; color: var(--text-secondary);
  line-height: 1.6;
}
.suggest-rationale em { color: var(--text-muted); font-style: normal; }

.review-empty {
  border: 1px dashed var(--border-strong); border-radius: 4px;
  padding: 14px 16px; font-size: 0.82rem; color: var(--text-secondary);
  background: var(--bg-card);
}
```

### 2.2 HTML — inject after the existing editor block

Inside `renderArticleModal`, right after the `if (live) { … }` editor section, add:

```js
// ---- LLM review ---------------------------------------------------
if (live) {
  html += `<div class="modal-section">
    <div class="modal-section-label">Review with LLM
      <span class="edit-note" style="margin-left:8px">
        the model proposes, you decide — nothing is written until you apply
      </span>
    </div>
    <div class="review-panel" id="reviewPanel">
      <div class="review-actions">
        <button class="btn btn-accent" id="reviewRunBtn">Suggest improvements</button>
        <label class="review-opt">
          <input type="checkbox" id="reviewIncludeContent">
          also review <code>content</code>
        </label>
        <span class="review-note" id="reviewStatus"></span>
      </div>
      <div id="reviewBody"></div>
    </div>
  </div>`;
}
```

### 2.3 JS — review flow + apply

Append to the script (near the payload-editor section). Everything routes through the existing `PATCH /payload` endpoint, so no new write path is introduced.

```js
/* ==================================================================
   LLM REVIEW
   ================================================================== */
function currentPayload() { return state.payload || null; }

function bindPayloadReview(article) {
  const runBtn  = document.getElementById('reviewRunBtn');
  const panel   = document.getElementById('reviewPanel');
  if (!runBtn) return;

  const includeContent = document.getElementById('reviewIncludeContent');
  const status = document.getElementById('reviewStatus');
  const body   = document.getElementById('reviewBody');

  runBtn.addEventListener('click', async () => {
    runBtn.disabled = true;
    runBtn.textContent = 'Reviewing…';
    status.textContent = 'Asking the model for suggestions…';
    body.innerHTML = '';
    try {
      const res = await apiFetch('/suggest', {
        method: 'POST',
        body: JSON.stringify({
          original_id: article.original_id,
          collection: article.collection,
          include_content: !!(includeContent && includeContent.checked)
        })
      });
      renderSuggestions(res, article);
      const n = (res.suggestions || []).length;
      status.textContent = n
        ? `${n} suggestion${n === 1 ? '' : 's'}`
        : 'No changes suggested — the payload looks consistent with the corpus.';
    } catch (e) {
      status.textContent = '';
      body.innerHTML = `<div class="edit-warn">Review failed: ${escapeHtml(e.message)}</div>`;
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = 'Suggest improvements';
    }
  });
}

function renderSuggestions(res, article) {
  const body = document.getElementById('reviewBody');
  const suggestions = res.suggestions || [];
  state.payloadSuggestions = suggestions;
  state.payloadSuggestionSel = suggestions.map(() => true);

  if (!suggestions.length) {
    body.innerHTML = `<div class="review-empty">
      The model did not find anything worth changing.
      ${res.fields_reviewed ? `<br><em>Fields reviewed:</em> ${escapeHtml(res.fields_reviewed.join(', '))}</em>` : ''}
    </div>`;
    return;
  }

  const cards = suggestions.map((s, i) => {
    const cur = fmtSuggestionValue(s.current);
    const sug = fmtSuggestionValue(s.suggested);
    return `
      <label class="suggest-card" data-conf="${escapeHtml(s.confidence)}" data-i="${i}">
        <div class="suggest-head">
          <input type="checkbox" class="suggest-cb" data-i="${i}" checked>
          <span class="field">${escapeHtml(s.field)}</span>
          <span class="conf ${escapeHtml(s.confidence)}">${escapeHtml(s.confidence)} confidence</span>
          <span class="spacer"></span>
        </div>
        <div class="suggest-diff">
          <div class="before"><span class="col">current</span>${cur}</div>
          <div class="after"><span class="col">suggested</span>${sug}</div>
        </div>
        ${s.rationale ? `<div class="suggest-rationale">${escapeHtml(s.rationale)}</div>` : ''}
      </label>`;
  }).join('');

  body.innerHTML = `
    <div class="suggest-list">${cards}</div>
    <div class="edit-actions">
      <button class="btn btn-accent" id="suggestApplyBtn">Apply selected</button>
      <button class="btn btn-ghost" id="suggestDiscardBtn">Discard</button>
      <span class="dirty-count" id="suggestCount">${suggestions.length} selected</span>
    </div>
    ${res.model ? `<div class="edit-note" style="margin-top:8px">model: <code>${escapeHtml(res.model)}</code>${
      res.usage ? ` · tokens: ${escapeHtml(JSON.stringify(res.usage))}` : ''
    }</div>` : ''}
  `;

  body.querySelectorAll('.suggest-cb').forEach(cb => {
    cb.addEventListener('change', () => {
      const i = Number(cb.dataset.i);
      state.payloadSuggestionSel[i] = cb.checked;
      cb.closest('.suggest-card').classList.toggle('is-off', !cb.checked);
      updateSuggestCount();
    });
  });

  document.getElementById('suggestApplyBtn').addEventListener('click', () =>
    applySuggestions(article));
  document.getElementById('suggestDiscardBtn').addEventListener('click', () => {
    state.payloadSuggestions = null;
    state.payloadSuggestionSel = null;
    body.innerHTML = '';
    document.getElementById('reviewStatus').textContent = '';
  });
}

function updateSuggestCount() {
  const count = (state.payloadSuggestionSel || []).filter(Boolean).length;
  const el = document.getElementById('suggestCount');
  if (el) el.textContent = `${count} selected`;
}

function fmtSuggestionValue(v) {
  if (v === null || v === undefined) return '<em>absent</em>';
  if (Array.isArray(v))              return escapeHtml(v.length ? v.join(', ') : '(empty list)');
  if (typeof v === 'object')         return escapeHtml(JSON.stringify(v));
  const s = String(v);
  if (!s)                            return '<em>(empty)</em>';
  return escapeHtml(s.length > 240 ? s.slice(0, 240) + '…' : s);
}

async function applySuggestions(article) {
  const suggestions = state.payloadSuggestions || [];
  const sel = state.payloadSuggestionSel || [];
  const patch = {};
  suggestions.forEach((s, i) => { if (sel[i]) patch[s.field] = s.suggested; });

  const chosen = Object.keys(patch).length;
  if (!chosen) { toast('No suggestions selected.', 'error'); return; }

  const target = article.collection;
  const detail = Object.entries(patch)
    .map(([k, v]) => `· ${k}`).join('\n');
  if (!confirm(`Apply ${chosen} field update(s) to ${target}?\n\n${detail}`)) return;

  const btn = document.getElementById('suggestApplyBtn');
  btn.disabled = true; btn.textContent = 'Applying…';
  try {
    const res = await apiFetch('/payload', {
      method: 'PATCH',
      body: JSON.stringify({
        original_id: article.original_id,
        fields: patch,
        collection: target
      })
    });
    toast(`Applied ${chosen} field update(s) to <code>${escapeHtml(article.original_id)}</code>.`, 'ok');
    state.payload = await apiFetch(
      `/article?original_id=${encodeURIComponent(article.original_id)}&collection=${encodeURIComponent(target)}`
    );
    renderArticleModal();
    await refreshStatus();
  } catch (e) {
    toast(`Apply failed: <code>${escapeHtml(e.message)}</code>`, 'error');
  } finally {
    btn.disabled = false; btn.textContent = 'Apply selected';
  }
}
```

Finally, hook it into the modal bootstrap: inside `renderArticleModal`, right after `if (live) bindPayloadEditor(article);` add:

```js
if (live) {
  bindPayloadEditor(article);
  bindPayloadReview(article);   // <— new
}
```

---

## 3. How the flow behaves on your two real examples

**`CL.CHIPENCOD.T3.C2.Art.148`** — the model sees `title: "Art. 148 — Art. 148 Código Penal Chileno"` and `doc_type: "unknown"`. Expected suggestions:

```
[✓] title      high   current:  "Art. 148 — Art. 148 Código Penal Chileno"
                       suggested: "Art. 148 — Código Penal Chileno"
                       rationale: "Redundant article prefix duplicated in the title."

[✓] doc_type   medium current:  "unknown"
                       suggested: "legislation"
                       rationale: "Source is the Chilean Penal Code, a national statute."
```

**`INT.AN10.T4.C2.S1.P4.Art.2.1.4.2.2`** — `theme: "Annex 10"` is already set, `doc_type: "unknown"` again. Expected:

```
[✓] doc_type   medium current:  "unknown"
                       suggested: "regulation"
                       rationale: "ICAO Annex, a regulatory instrument under the Chicago Convention."
```

**`CL.ChileanCivilCodeandRelatedLaws.Art.2\`** — the trailing backslashes are a parser bug the model can also flag (but the UI shows these as `suggested` values, so a human decides):

```
[✓] eli_id*    — NOT suggested (immutable)
[ ] title      high   current:  "§ 2\\. Promulgation of the Law"
                       suggested: "§ 2. Promulgation of the Law"
                       rationale: "Stray Markdown escape character in title."
```

`eli_id` is in `_IMMUTABLE_FIELDS`, so the model can never propose it — that's a corpus-regeneration problem, not a payload-edit problem.

---

## 4. Guardrails worth keeping

- **Nothing is written by the review itself.** The LLM call is a `POST /suggest`; the write is still the same `PATCH /payload` you already trust.
- **Field allow-list on both ends.** The frontend only offers editable fields; the backend re-filters against `EDITABLE_PAYLOAD_FIELDS`.
- **`content` is opt-in.** Off by default because content edits are the highest-risk case for hallucination.
- **`current != suggested` check.** The router drops no-op suggestions, so the UI never shows a green arrow that goes nowhere.
- **Confidence is visible.** Low-confidence rows get a distinct border so a reviewer can skim past them.
- **`confirm()` before apply.** Same safeguard as the force reindex path.
- **LLM provider is behind one function.** Swapping OpenAI for Anthropic/Claude/Ollama/a local model is a one-file change in `src/infrastructure/llm.py`.
- **Telemetry is returned, not logged.** `res.model` and `res.usage` come back in the response so you can display them — and later bill them — without extra plumbing.

---
