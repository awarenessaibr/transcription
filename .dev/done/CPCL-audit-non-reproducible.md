> **ARCHIVED — non-reproducible. Superseded by `03.md`.**
>
> This audit was written against an external bundle, `CPCL.txt`, which is **not
> present anywhere in this workspace** (`find` over `mcp-ecosystem/` returns no
> such file), and its vocabulary (`established`, `candidate`, `cached in …`,
> `no framework code yet`) does not correspond to any field in the corpus. Its
> concrete identifiers are therefore IDs from a foreign pipeline and were not
> reproducible here.
>
> Verified counter-analysis, with per-claim verdicts and the defects that
> genuinely need fixing, is in **`.dev/ongoing/03.md`**
> (`Law Corpus Correction Report — data/law`). That report supersedes this one.
>
> Archived 2026-09-19. Original text follows verbatim.

---

# Audit Report — `CPCL.txt` Findings

## Scope and basis
This report is based **only on the annotations inside `CPCL.txt`**. It does not independently verify Chilean legal text, article numbering, or official sources. The file itself contains provenance notes such as:

- `established` vs `candidate`
- `from the bundle's ...`
- `no text in this bundle's caches, and the ingested corpus has no record`
- `cached in ... which is not this article's statute`
- `no framework code yet`

Those notes are the evidence for the issues below.

---

## Executive summary
The bundle contains **19 article entries**.

- **Established:** 3  
- **Candidate:** 16  
- **Missing from cache/corpus:** 4  
- **Cached under the wrong statute:** 5  
- **No framework code yet:** 3  
- **Candidate but otherwise no explicit issue:** 4  

Main problems:

1. Several articles have **no source text** in the bundle or ingested corpus.
2. Several articles are cached under the **wrong statute file**.
3. Some articles have **no framework code assigned**.
4. Most entries are still only **candidate**, not established.
5. Statute labels and namespaces are **inconsistent** — especially `CPCL` vs `CODIGOPENAL` and `CPR` vs `CONST`/`Constitucion`.

---

## What is wrong, why, and what needs to change

### 1. Missing source text / no corpus record
**Affected entries:**
- `CL.CPCL.Art.256` — Abuso de autoridad por denegación de auxilio o falta de cumplimiento de deberes
- `CL.CPCL.Art.257` — Abuso de autoridad por negativa a recibir denuncia o querella
- `CL.LPDC.Art.56` — Procedimiento ante el Servicio Nacional del Consumidor y denuncia de infracciones
- `CL.CPR.Art.19.2` — Garantía de igualdad ante la ley y prohibición de discriminación arbitraria

**Why it is wrong:**  
The file explicitly says there is no cached text and no ingested-corpus record. These entries cannot be verified, cited, or reliably used.

**What needs to change:**  
- Ingest the authoritative text for each article.
- Re-index the bundle/cache.
- Re-run the resolution/audit.
- Promote to `established` only after verification.

---

### 2. Wrong statute / wrong cache association
**Affected entries:**
- `CL.CPCL.Art.193`
- `CL.CPCL.Art.194`
- `CL.CPCL.Art.197`
- `CL.CPCL.Art.211`
- `CL.CPR.Art.19.3`

**Why it is wrong:**  
The file says these are cached in files such as `CHIPENCOD.md` or `Constitucion.md`, but those are **not this article’s statute**. This creates cross-statute contamination and can cause wrong retrieval, wrong citations, and wrong framework mapping.

**What needs to change:**  
- Re-cache each article under its correct statute file.
- Align the framework code with the correct statute.
- Remove or mark the wrong-cache entry as a cross-reference only.
- For `CL.CPR.Art.19.3`, resolve whether the canonical code is `CL.CPR` or `CL.CONST`/`CONSTITUCION`.

---

### 3. No framework code yet
**Affected entries:**
- `CL.CPCL.C1.Art.228` — Prevaricación – Empleado público no judicial
- `CL.CPCL.C1.Art.229` — Prevaricación – Omisión de persecución o aprehensión
- `CL.LPDC.T1.Art.3.e` — Derecho a Reparación e Indemnización

**Why it is wrong:**  
Without a framework code, these entries cannot be normalized, linked, grouped, or validated against the ontology.

**What needs to change:**  
- Assign the correct canonical framework code.
- Confirm the article belongs to the stated statute.
- Update metadata and re-audit.

---

### 4. Candidate status not yet validated
**Affected entries include:**
- `CL.CPCL.C1.Art.269_ter`
- `CL.LPDC.Art.12`
- `CL.CPCL.T2.P7.Art.416`
- `CL.CPCL.C1.Art.224`
- plus most entries already listed under missing/wrong-cache/no-framework issues

**Why it is wrong:**  
`candidate` means the entry is not yet authoritative. Some are sourced from a bundle, but they still need validation.

**What needs to change:**  
- Validate against an official or trusted source.
- If correct, promote to `established`.
- If incorrect, fix the identifier, title, statute, or remove the entry.

---

### 5. Inconsistent statute labels and namespaces
**Observed issue:**  
The file has section headings such as `CPCL`, `LPDC`, and `CODIGOPENAL`, but entries under `CODIGOPENAL` still use identifiers like `CL.CPCL.C1.Art.228`. Similarly, `CL.CPR.Art.19.3` is cached under `Constitucion.md` with codes like `CL.CONST`, `CONST`, `CONSTITUCION`.

**Why it is wrong:**  
This suggests duplicate or conflicting canonical names. It makes grouping, retrieval, and audit rules unreliable.

**What needs to change:**  
- Choose one canonical statute code per body of law.
- Decide whether `CPCL` and `CODIGOPENAL` are the same or different.
- Decide whether `CPR` and `CONST`/`CONSTITUCION` are the same.
- Normalize all identifiers and section headings.
- Standardize article suffix formatting, e.g. `Art.269_ter` vs `Art.269 ter`.

---

## Recommended remediation plan

### Priority 0 — Data integrity blockers
1. Ingest missing texts:
   - `CL.CPCL.Art.256`
   - `CL.CPCL.Art.257`
   - `CL.LPDC.Art.56`
   - `CL.CPR.Art.19.2`
2. Re-cache wrong-statute entries:
   - `CL.CPCL.Art.193`
   - `CL.CPCL.Art.194`
   - `CL.CPCL.Art.197`
   - `CL.CPCL.Art.211`
   - `CL.CPR.Art.19.3`

### Priority 1 — Framework and normalization
3. Assign framework codes to:
   - `CL.CPCL.C1.Art.228`
   - `CL.CPCL.C1.Art.229`
   - `CL.LPDC.T1.Art.3.e`
4. Canonicalize statute codes:
   - `CPCL` vs `CODIGOPENAL`
   - `CPR` vs `CONST`/`CONSTITUCION`
5. Normalize identifier formatting.

### Priority 2 — Validation and promotion
6. Validate all `candidate` entries.
7. Promote correct entries to `established`.
8. Correct or remove incorrect entries.
9. Re-run the bundle audit and confirm no remaining `no framework code`, `wrong statute`, or `no record` notes.

---

## Bottom line
The main issue is **metadata and provenance integrity**, not necessarily the legal content itself. The bundle has:

- missing texts,
- wrong cache/statute associations,
- missing framework codes,
- too many unvalidated candidates,
- inconsistent statute naming.

Fixing these requires re-ingesting missing sources, correcting cache locations, assigning canonical framework codes, normalizing statute labels, and validating candidate entries before promotion.