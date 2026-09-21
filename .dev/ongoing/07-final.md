## Best fix order

### 1. Choose canonical statutes/ELIs
Right now you have multiple ELI families for the same Chilean material:

| Cited as | Audit uses | Likely canonical |
|---|---|---|
| `CL.CPCL.Art.256` | `CL.CPCL.C1.Art.256` | `CL.CPCL.C1.Art.256` |
| `CL.CPCL.Art.257` | `CL.CPCL.C1.Art.257` | `CL.CPCL.C1.Art.257` |
| `CL.CPR.Art.19.2` | `CL.CONST.T1.C3.P2.Art.19.2` | `CL.CONST...` |
| `CL.CPR.Art.19.3` | `CL.CONST.T1.C3.P3.Art.19.3` | `CL.CONST...` |
| `CL.CPCL.Art.193/194/197/211` | `CL.CHIPENCOD...` | re-label to `CL.CPCL...` if same code |
| `CL.LPDC.Art.56` | `CL.L19496.Art.56` | `CL.LPDC.Art.56` |

Then either:
- re-ELI the local files and Qdrant points to the canonical ELI, or
- add a strict alias map so the citation checker resolves `CL.CPR` → `CL.CONST`, `CL.L19496` → `CL.LPDC`, etc.

### 2. Ingest missing local articles
These are **not** “different text” or “no text” — they are local files that were never put into Qdrant:

- `CL.CPCL.C1.Art.228`
- `CL.CPCL.C1.Art.229`
- `CL.CPCL.C1.Art.256`
- `CL.CPCL.C1.Art.257`
- `CL.CPCL.C1.Art.224`
- `CL.CONST.T1.C3.P2.Art.19.2`
- `CL.L19496.Art.56`
- and the other `CL.L19496.Art.56A–H` if needed

Action: ingest those local files into Qdrant under canonical ELIs. Do not delete them.

### 3. Resolve drift
The audit lists these as `content_drift_eli`, meaning local text and Qdrant text differ:

- `CL.LPDC.T1.Art.3.b`
- `CL.LPDC.T1.Art.3.e`
- `CL.LPDC.Art.23`
- `CL.LPDC.Art.12`
- `CL.CPCL.C1.Art.269_ter`

Action:
- Decide which side is authoritative.
- If local file is authoritative: delete the Qdrant point for that ELI and re-ingest the local file.
- If Qdrant is authoritative: update the local file from Qdrant.
- Re-run audit until `content_drift: 0`.

### 4. Merge or delete wrong-statute caches
Examples:
- `CHIPENCOD_CP.md` contains `CL.CHIPENCOD.T4.C3.Art.193`, `194`, `197`, `CL.CHIPENCOD.T4.C6.Art.211`, etc. If these are the Chilean Penal Code, either re-label them to `CL.CPCL...` and re-ingest, or keep them only as aliases. Do not leave them as the only source for a `CL.CPCL` citation.
- `Constitucion.md` uses `CL.CONST...` but the report cites `CL.CPR...`. Standardize on `CL.CONST` and either re-label the citations or add aliases.
- `CL.L19496.Art.56` should probably become `CL.LPDC.Art.56`.

If you standardize on one canonical family, you can delete the duplicate alias files after merging their unique articles.

## Concrete triage for the 19 cited articles

| Cited article | Audit reality | Best action |
|---|---|---|
| `CL.CPCL.C1.Art.255` | In Qdrant, no drift | OK |
| `CL.LPDC.T1.Art.3.b` | In Qdrant, but drift | Resolve drift / re-ingest |
| `CL.LPDC.Art.23` | In Qdrant, but drift | Resolve drift / re-ingest |
| `CL.CPCL.C1.Art.269_ter` | In Qdrant, but drift | Resolve drift / re-ingest |
| `CL.CPCL.C1.Art.228` | Missing from Qdrant, local file exists | Ingest local file; fix report |
| `CL.CPCL.Art.256` | Local `CL.CPCL.C1.Art.256` exists, missing Qdrant | Ingest; fix ELI |
| `CL.CPCL.Art.257` | Local `CL.CPCL.C1.Art.257` exists, missing Qdrant | Ingest; fix ELI |
| `CL.CPCL.C1.Art.229` | Missing from Qdrant, local file exists | Ingest local file |
| `CL.CPCL.Art.193` | Only in `CHIPENCOD` | Re-label/merge into `CL.CPCL` or alias |
| `CL.CPCL.Art.194` | Only in `CHIPENCOD` | Re-label/merge into `CL.CPCL` or alias |
| `CL.CPCL.Art.197` | Only in `CHIPENCOD` | Re-label/merge into `CL.CPCL` or alias |
| `CL.LPDC.Art.12` | In Qdrant, but drift | Resolve drift / re-ingest |
| `CL.LPDC.T1.Art.3.e` | In Qdrant, but drift | Resolve drift / re-ingest |
| `CL.LPDC.Art.56` | Local `CL.L19496.Art.56` exists, missing Qdrant | Merge/re-ELI to `CL.LPDC.Art.56`, ingest |
| `CL.CPR.Art.19.2` | Local `CL.CONST.T1.C3.P2.Art.19.2` exists, missing Qdrant | Standardize to `CL.CONST`, ingest |
| `CL.CPR.Art.19.3` | In Qdrant as `CL.CONST.T1.C3.P3.Art.19.3` | Standardize ELI |
| `CL.CPCL.Art.211` | Only in `CHIPENCOD` | Re-label/merge into `CL.CPCL` or alias |
| `CL.CPCL.T2.P7.Art.416` | In Qdrant, no drift | OK |
| `CL.CPCL.C1.Art.224` | Missing from Qdrant; `CodigoPenal_Prevaricacion.md` has 8 articles, none ingested | Ingest whole prevaricación file |

## What to delete

Safe to delete, after merging unique text:

- Qdrant points for ELIs in `content_drift_eli` before re-ingesting.
- Duplicate alias files, e.g. `CL.CPR` aliases if you standardize on `CL.CONST`.
- `CL.L19496.*` individual files after merging into `CL.LPDC.*`.
- `CHIPENCOD` duplicate entries after moving their unique articles into canonical `CL.CPCL.*`.
- Empty/placeholder local files.
- Stale derived reports — regenerate them from the audit.

**Do not delete**:

- `CL/CL.CPCL.C1.Art.228.md`
- `CL/CL.CPCL.C1.Art.229.md`
- `CL/CL.CPCL.C1.Art.256.md`
- `CL/CL.CPCL.C1.Art.257.md`
- `CL/CodigoPenal_Prevaricacion.md`
- `CL/Constitucion.md`
- `CL/CL.L19496.Art.56.md`

These are the only local sources for articles that are missing from Qdrant. Ingest them instead.

## Verification

After fixing, re-run the audit. You want:

- `validation_ok: true`
- `missing_eli: []`
- `content_drift: 0`
- `colliding_elis: 0`
- `alias_only_same_article_already_ingested` reduced to only intentional aliases

Then regenerate the first “19 article(s)” report from the corrected audit. Do not hand-edit that report.