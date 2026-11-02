# Narration Aligner — Plan & Code

**Goal:** a tiny UI: upload `audio` + `text` → get `start_ms,end_ms,page,text` CSV.

**Approach:** your running server already exposes Whisper transcription (`/api/diarization/transcribe`). We'll build a small wrapper that:

1. Forwards the audio to your server with `skip_diarization=true` and **`remove_silence=false`** (critical — otherwise timestamps won't line up with the original audio).
2. Parses the source text (plain lines, `Página N` markers, or a pre-existing CSV).
3. Aligns each source line to a **contiguous, monotonic block of Whisper segments** using an O(n·m) DP (with a word+char fuzzy similarity).
4. Emits the CSV.

You don't need to touch the existing server at all.

---

### `requirements.txt`
```txt
fastapi>=0.110
uvicorn[standard]>=0.27
httpx>=0.27
python-multipart>=0.0.9
jinja2>=3.1
```

---

### `aligner.py`
```python
"""Align source narration lines to Whisper segments via O(n*m) dynamic programming."""
from __future__ import annotations

import csv
import difflib
import io
import re
from typing import Dict, List, Tuple


# ---------- similarity -------------------------------------------------------

_PUNCT = re.compile(r"[^\w\sáéíóúâêîôûãõàèìòùäëïöüçñ]", re.IGNORECASE)
_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    s = s.lower()
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    return s


def text_similarity(a: str, b: str) -> float:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    char_ratio = difflib.SequenceMatcher(None, a, b).ratio()
    wa, wb = set(a.split()), set(b.split())
    word_ratio = len(wa & wb) / len(wa | wb) if (wa and wb) else 0.0
    return 0.6 * char_ratio + 0.4 * word_ratio


# ---------- input parsing ----------------------------------------------------

_PAGE_RE = re.compile(
    r"^\s*p[áa]gina\s+([\w\-]+)\s*[:\-–—]?\s*(.*)$", re.IGNORECASE
)


def parse_input_text(content: str) -> List[Dict[str, str]]:
    """Parse an uploaded source text into [{text, page}, ...].

    Supports:
      * CSV with header start_ms,end_ms,page,text  → re-aligns its `text` column
      * Plain lines, optionally preceded by "Página N" markers
    """
    content = content.lstrip("\ufeff")
    lines = content.splitlines()
    first_nonempty = next((l.strip() for l in lines if l.strip()), "")

    # Case 1: already a CSV
    if first_nonempty.lower().startswith("start_ms"):
        reader = csv.DictReader(io.StringIO(content))
        out: List[Dict[str, str]] = []
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            page = (row.get("page") or "0").strip() or "0"
            out.append({"text": text, "page": page})
        return out

    # Case 2: plain text, optional Página markers
    out = []
    page = "0"
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith('"') and line.endswith('"') and len(line) > 1:
            line = line[1:-1]

        m = _PAGE_RE.match(line)
        if m:
            page = m.group(1)
            rest = m.group(2).strip()
            if rest:
                # "Página N, <content>" — keep as a real spoken target
                out.append({"text": line, "page": page})
            # else: pure page marker, no target
            continue

        out.append({"text": line, "page": page})
    return out


# ---------- alignment --------------------------------------------------------

EMPTY_PENALTY = 1.5   # a source line with no matching segment
STEP_EPS = 0.01       # tiny tax on every segment to prefer compact blocks
INF = float("inf")


def align_lines_to_segments(
    targets: List[Dict[str, str]],
    segments: List[Dict[str, float]],
) -> List[Tuple[int, int]]:
    """Return a list of (k, j) ranges per target meaning segments[k:j].

    Every segment is assigned to exactly one target; ranges are contiguous
    and monotonic; empty ranges (k == j) are allowed at a penalty.
    """
    n, m = len(targets), len(segments)
    if n == 0:
        return []
    if m == 0:
        return [(0, 0)] * n

    # Similarity + prefix sums per target
    PS: List[List[float]] = []
    for i in range(n):
        row = [0.0] * (m + 1)
        ti = targets[i]["text"]
        for j in range(m):
            row[j + 1] = row[j] + text_similarity(ti, segments[j]["text"])
        PS.append(row)

    # dp[i][j] = min cost having placed targets 0..i-1 over segments 0..j-1
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[-1] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0

    for i in range(n):
        row = PS[i]
        Q = [j - row[j] for j in range(m + 1)]   # cost(k,j) = Q[j]-Q[k]+eps for j>k
        best_val, best_k = INF, -1

        for j in range(m + 1):
            # A) target i is empty
            if dp[i][j] + EMPTY_PENALTY < dp[i + 1][j]:
                dp[i + 1][j] = dp[i][j] + EMPTY_PENALTY
                back[i + 1][j] = j  # k == j

            # B) target i takes segments [k, j) — non-empty
            if j > 0:
                k = j - 1
                if dp[i][k] < INF:
                    v = dp[i][k] - Q[k]
                    if v < best_val:
                        best_val, best_k = v, k
                if best_val < INF:
                    cand = Q[j] + STEP_EPS + best_val
                    if cand < dp[i + 1][j]:
                        dp[i + 1][j] = cand
                        back[i + 1][j] = best_k

    # Backtrack
    assignments: List[Tuple[int, int]] = [(0, 0)] * n
    j = m
    for i in range(n, 0, -1):
        k = back[i][j]
        if k < 0:
            k = j
        assignments[i - 1] = (k, j)
        j = k
    return assignments


# ---------- rows / csv -------------------------------------------------------

def build_rows(
    targets: List[Dict[str, str]],
    segments: List[Dict[str, float]],
    assignments: List[Tuple[int, int]],
) -> List[Dict]:
    n = len(targets)
    resolved: List[Tuple[float, float] | None] = [None] * n
    for i, (k, j) in enumerate(assignments):
        if k < j:
            resolved[i] = (float(segments[k]["start"]), float(segments[j - 1]["end"]))

    # Interpolate empty lines
    for i in range(n):
        if resolved[i] is not None:
            continue
        prev_end = 0.0
        for p in range(i - 1, -1, -1):
            if resolved[p] is not None:
                prev_end = resolved[p][1]
                break
        nxt = None
        for p in range(i + 1, n):
            if resolved[p] is not None:
                nxt = resolved[p][0]
                break
        if nxt is None:
            nxt = prev_end + 0.5
        mid = (prev_end + nxt) / 2.0
        resolved[i] = (mid, mid)

    # Enforce monotonicity
    for i in range(1, n):
        assert resolved[i] is not None and resolved[i - 1] is not None
        if resolved[i][0] < resolved[i - 1][1]:
            resolved[i] = (resolved[i - 1][1], resolved[i][1])

    rows = []
    for t, (s, e) in zip(targets, resolved):
        assert s is not None and e is not None
        rows.append(
            {
                "start_ms": int(round(s * 1000)),
                "end_ms": int(round(e * 1000)),
                "page": t["page"],
                "text": t["text"],
            }
        )
    return rows


def rows_to_csv(rows: List[Dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["start_ms", "end_ms", "page", "text"])
    for r in rows:
        w.writerow([r["start_ms"], r["end_ms"], r["page"], r["text"]])
    return buf.getvalue()
```

---

### `main.py`
```python
import io
import os
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from aligner import (
    align_lines_to_segments,
    build_rows,
    parse_input_text,
    rows_to_csv,
)

# Where the existing transcription server lives
API_BASE = os.environ.get("TRANSCRIBE_API_BASE", "http://localhost:8000")
DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")

HERE = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(HERE, "templates"))

app = FastAPI(title="Narration Aligner")


# ---------- response normalisation ------------------------------------------

def _extract_segments(payload: Any) -> List[Dict[str, float]] | None:
    """Find a list of {start, end, text} inside whatever the server returned."""
    if isinstance(payload, list):
        return _normalize(payload)
    if isinstance(payload, dict):
        for key in ("segments", "transcription", "result", "data", "output"):
            if key in payload:
                got = _extract_segments(payload[key])
                if got is not None:
                    return got
        for v in payload.values():
            if isinstance(v, (dict, list)):
                got = _extract_segments(v)
                if got is not None:
                    return got
    return None


def _normalize(items: Any) -> List[Dict[str, float]] | None:
    if not isinstance(items, list):
        return None
    out: List[Dict[str, float]] = []
    for s in items:
        if not isinstance(s, dict):
            continue
        try:
            start = float(s.get("start", s.get("start_time", 0.0)) or 0.0)
            end = float(s.get("end", s.get("end_time", 0.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        text = str(s.get("text", "") or "")
        out.append({"start": start, "end": end, "text": text})
    return out or None


# ---------- UI ---------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {"ok": True, "api_base": API_BASE}


# ---------- main endpoint ---------------------------------------------------

@app.post("/api/align")
async def align(
    audio: UploadFile = File(...),
    text: UploadFile = File(...),
    language: str = Form("pt"),
    whisper_model: str = Form(DEFAULT_MODEL),
):
    audio_bytes = await audio.read()
    text_bytes = await text.read()
    if not audio_bytes:
        raise HTTPException(400, "Empty audio upload.")
    if not text_bytes:
        raise HTTPException(400, "Empty text upload.")

    try:
        text_content = text_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text_content = text_bytes.decode("latin-1", errors="replace")

    targets = parse_input_text(text_content)
    if not targets:
        raise HTTPException(400, "No target lines found in the text file.")

    # Forward to the existing transcription server
    files = {
        "file": (
            audio.filename or "audio.wav",
            audio_bytes,
            audio.content_type or "application/octet-stream",
        )
    }
    data = {
        "language": language,
        "whisper_model": whisper_model,
        "skip_diarization": "true",       # we only need text + timings
        "remove_silence": "false",        # KEEP original timeline!
        "noise_reduce": "true",
        "voice_enhance": "true",
        "apply_gain": "true",
        "word_timestamps": "false",
    }

    timeout = httpx.Timeout(1800.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                f"{API_BASE}/api/diarization/transcribe",
                files=files,
                data=data,
            )
        except httpx.RequestError as e:
            raise HTTPException(502, f"Transcription server unreachable: {e}")

    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, f"Transcription failed: {resp.text[:800]}")

    try:
        payload = resp.json()
    except Exception:
        raise HTTPException(502, "Transcription server did not return JSON.")

    segments = _extract_segments(payload)
    if not segments:
        raise HTTPException(
            500, f"No segments found in transcription response: {str(payload)[:500]}"
        )

    assignments = align_lines_to_segments(targets, segments)
    rows = build_rows(targets, segments, assignments)
    csv_text = rows_to_csv(rows)

    return JSONResponse(
        {
            "csv": csv_text,
            "rows": rows,
            "targets_count": len(targets),
            "segments_count": len(segments),
        }
    )
```

---

### `templates/index.html`
```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Narration Aligner</title>
<style>
  :root { font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  body { margin: 0; padding: 32px; background: #f6f7fb; color: #111; }
  .container { max-width: 980px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 6px; }
  .sub { color: #666; margin-bottom: 24px; font-size: 14px; }
  .card { background: #fff; border-radius: 12px; padding: 24px;
          box-shadow: 0 1px 3px rgba(0,0,0,.06); margin-bottom: 16px; }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .drop { border: 2px dashed #cfd4dd; border-radius: 10px; padding: 24px;
          text-align: center; cursor: pointer; transition: all .15s; }
  .drop.dragover { border-color: #3b82f6; background: #eff6ff; }
  .drop.has-file { border-color: #10b981; background: #ecfdf5; }
  .drop .name { font-weight: 600; margin-top: 6px; word-break: break-all; }
  .drop .hint { color: #888; font-size: 13px; }
  label.field { display: block; margin-bottom: 12px; }
  label.field span { font-size: 13px; color: #555; display: block; margin-bottom: 4px; }
  input[type=text] { width: 100%; padding: 8px 10px; border: 1px solid #d1d5db;
                     border-radius: 8px; font-size: 14px; box-sizing: border-box; }
  button { background: #3b82f6; color: #fff; border: 0; padding: 10px 20px;
           border-radius: 8px; font-size: 15px; font-weight: 600; cursor: pointer; }
  button:disabled { background: #93c5fd; cursor: not-allowed; }
  button.secondary { background: #10b981; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { padding: 8px; border-bottom: 1px solid #eee; text-align: left;
           vertical-align: top; }
  th { background: #fafafa; font-size: 11px; text-transform: uppercase;
       color: #666; letter-spacing: .04em; }
  .status { padding: 12px; border-radius: 8px; margin-top: 14px; font-size: 14px; }
  .status.ok { background: #ecfdf5; color: #065f46; }
  .status.err { background: #fef2f2; color: #991b1b; }
  .status.loading { background: #eff6ff; color: #1e40af; }
  .hidden { display: none; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 12px; color: #444; }
</style>
</head>
<body>
<div class="container">
  <h1>Narration Aligner</h1>
  <div class="sub">Upload the narration audio and the source text → get a
    timestamped <code>start_ms,end_ms,page,text</code> CSV.</div>

  <div class="card">
    <div class="row">
      <div>
        <label class="field"><span>Audio file</span></label>
        <div class="drop" id="dropAudio">
          <div class="hint">Click or drop audio here</div>
          <div class="name" id="nameAudio"></div>
          <input type="file" id="fileAudio" accept="audio/*,video/*" hidden>
        </div>
      </div>
      <div>
        <label class="field"><span>Text file</span></label>
        <div class="drop" id="dropText">
          <div class="hint">Click or drop text/CSV here</div>
          <div class="name" id="nameText"></div>
          <input type="file" id="fileText" accept=".txt,.csv,text/*" hidden>
        </div>
      </div>
    </div>

    <div class="row" style="margin-top:16px;">
      <label class="field"><span>Language</span>
        <input type="text" id="language" value="pt">
      </label>
      <label class="field"><span>Whisper model</span>
        <input type="text" id="model" value="large-v3">
      </label>
    </div>

    <button id="go" disabled>Align &amp; generate CSV</button>
    <div id="status" class="status hidden"></div>
  </div>

  <div id="resultCard" class="card hidden">
    <div style="display:flex; justify-content: space-between; align-items:center;
                margin-bottom:12px;">
      <strong id="resultSummary"></strong>
      <button class="secondary" id="download">Download CSV</button>
    </div>
    <div style="max-height: 420px; overflow:auto;">
      <table id="preview">
        <thead><tr><th>start_ms</th><th>end_ms</th><th>page</th><th>text</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
let audioFile = null, textFile = null, csvText = '';

function wireDrop(dropId, inputId, nameId, set) {
  const drop = $(dropId), input = $(inputId), name = $(nameId);
  drop.addEventListener('click', () => input.click());
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('dragover'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
  drop.addEventListener('drop', e => {
    e.preventDefault(); drop.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      input.files = e.dataTransfer.files;
      input.dispatchEvent(new Event('change'));
    }
  });
  input.addEventListener('change', () => {
    if (!input.files.length) return;
    set(input.files[0]);
    name.textContent = input.files[0].name;
    drop.classList.add('has-file');
    check();
  });
}
wireDrop('dropAudio', 'fileAudio', 'nameAudio', f => audioFile = f);
wireDrop('dropText',  'fileText',  'nameText',  f => textFile  = f);

function check() { $('go').disabled = !(audioFile && textFile); }

$('go').addEventListener('click', async () => {
  const btn = $('go'), status = $('status');
  btn.disabled = true;
  status.className = 'status loading';
  status.textContent = 'Uploading & transcribing… this can take a while for long audio.';
  status.classList.remove('hidden');

  const fd = new FormData();
  fd.append('audio', audioFile);
  fd.append('text',  textFile);
  fd.append('language', $('language').value || 'pt');
  fd.append('whisper_model', $('model').value || 'large-v3');

  try {
    const r = await fetch('/api/align', { method: 'POST', body: fd });
    if (!r.ok) {
      const t = await r.text();
      throw new Error(t || ('HTTP ' + r.status));
    }
    const data = await r.json();
    showResult(data);
    status.className = 'status ok';
    status.textContent = `Done — ${data.targets_count} lines aligned against `
                       + `${data.segments_count} Whisper segments.`;
  } catch (e) {
    status.className = 'status err';
    status.textContent = 'Error: ' + (e.message || e);
  } finally {
    btn.disabled = false;
    check();
  }
});

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function showResult(data) {
  $('resultCard').classList.remove('hidden');
  $('resultSummary').textContent = `${data.rows.length} rows`;
  const tbody = $('preview').querySelector('tbody');
  tbody.innerHTML = '';
  for (const row of data.rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td class="mono">${row.start_ms}</td>`
                 + `<td class="mono">${row.end_ms}</td>`
                 + `<td>${escapeHtml(String(row.page))}</td>`
                 + `<td>${escapeHtml(row.text)}</td>`;
    tbody.appendChild(tr);
  }
  csvText = data.csv;
}

$('download').addEventListener('click', () => {
  const blob = new Blob([csvText], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'aligned.csv';
  a.click();
  URL.revokeObjectURL(a.href);
});
</script>
</body>
</html>
```

---

### Run it

```bash
pip install -r requirements.txt

# point at your already-running transcription server
export TRANSCRIBE_API_BASE="http://localhost:8000"
export WHISPER_MODEL="large-v3"   # optional

uvicorn main:app --host 0.0.0.0 --port 8080
```

Open <http://localhost:8080>, drop in the audio and the text, click **Align**.

---

### Why this works

- **Whisper is used as a "time oracle"**, not as the transcript source. Its text may be imperfect — we ignore that. We only need *where* speech happens.
- **`remove_silence=false` is non-negotiable** — otherwise Whisper’s reported seconds refer to a *trimmed* timeline and every timestamp shifts.
- The DP enforces: (a) each source line maps to a **contiguous block** of Whisper segments, (b) blocks are **monotonic** across the file, (c) every Whisper segment is used. This exactly matches how narration lines correspond to speech runs.
- The cost `(j−k) − (Σ sim) + ε` collapses to `Q[j] − Q[k] + ε` with `Q[j] = j − prefix_sim[j]`, giving **O(n·m)** alignment even for long files (a 300-line/300-segment story runs in well under a second).
- Line-level fuzzy similarity is a 60/40 char-Jaccard hybrid — robust to Whisper’s small spelling mistakes but sensitive enough to distinguish adjacent lines.