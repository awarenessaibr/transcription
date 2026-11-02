# Pinocchio UI — `File & Execution` Deep Review

**Scope:** the main working surface of `templates/pinocchio-en.html` (the card titled
**File & Execution**, its sibling panels, and the *Settings* modal that feeds it), the full
configuration path from browser control → HTTP form field → backend DSP → Whisper, and the
audio-manipulation features adopted from the sibling `audio/` project.

**Method:** source read of the 7,483-line template, the FastAPI routers, the use cases and the
`pydub`/`noisereduce` processor; plus a live capability probe of the `audio/` service
(`127.0.0.1:8777`) and the `audio/` MCP bridge (`127.0.0.1:8765`). All line citations are as of
this review.

**Verdict in one line:** the UI exposes a rich, genuinely useful parameter surface, but
**eight of the visible controls were inert, three were silently discarded by the server, two
provider paths lost every preprocessing flag, and the "voice enhance" stage tilted the 3.4–8 kHz
fricative band down by 6–8 dB** — i.e. the panel over-promised relative to what the pipeline
executed. §5 records the fixes applied in this pass; §7 is the remaining backlog.

---

## 1. What "File & Execution" actually is

`File & Execution` is the left column of the `#exec .grid-main` block
(`pinocchio-en.html:1961-2037`). It is deliberately thin — it owns *file intake, progress,
and the segment table*, and delegates everything else to sibling cards and to the
`Critical Configuration` card above it.

```
Critical Configuration · Endpoint & Transcription   (1730-1867)  ← provider + transport + 8 core params
Project Journey & Reference Priors                  (1870-1958)  ← project / priors / guided+async routing
#exec .grid-main
 ├─ File & Execution                                 (1964-2037)  ← THE MAIN PART
 │    fileDropArea → drag & drop / multi-select      (1967-1971)
 │    Hide empty · Queue · Endpoint readout          (1972-1980)
 │    runStatus badge + elapsed timer                (1981-1984)
 │    progressLabel + bar + 4 stages                 (1985-1994)
 │    summary chips                                  (1996)
 │    SEGMENTS table (Sel/#/Speaker/Start/End/Dur/Text) (1998-2017)
 │    Import selected audio (dropdown) · Export ZIP  (2018-2033)
 ├─ Speakers                     (registry resolution)      (2039-2058)
 ├─ Voiceprint Library           (waveform, region, clips)   (2060-2109)
 ├─ Comparison panel             (excerpt A/B merge)         (2112-2145)
 ├─ Saved & Comparative Analyses                             (2150-2185)
 ├─ Validate & Refine            (audit · patch · acoustic)  (2188-2252)
 └─ Transcript Curation & Review (review + retranscribe)    (2255-2388)
```

**Execution flow** (`handleAudioSelection` → `handleTranscription`, `4692-4703` / `4632-4690`):

1. `extractMetadata(file)` (exifr, `4276-4285`) — client-side EXIF/GPS/device sniffing.
2. `buildConfig()` (`4296-4330`) — flattens the DOM into one flat object.
3. Provider dispatch (`4657-4666`): `runpod` → base64 to `api.runpod.ai/v2/{id}`;
   `pyannote` → `POST /api/pinocchio/transcribe/pyannote`; else **local** →
   `POST /api/pinocchio/transcribe` with the whole config as multipart form fields.
4. `transcribeLocal` (`4559-4577`) appends *every non-null config key* (`4565-4567`) and posts
   through `postTranscriptionWithFallback` (`3208-3254`), which walks a candidate URL list and
   **upgrades the route to the guided / guided-async endpoints** when a project is selected
   (`3211-3225`).
5. Result → `renderSegments` / `renderSummary` / `renderTimings` → `autoStoreCompletedRun`.

`/api/pinocchio/*` is a pure alias layer: 307 redirects onto `/api/diarization/*`
(`src/presentation/routers/pinocchio.py:57-120`), and 307 preserves method *and* body, so
multipart uploads survive.

---

## 2. Complete configuration inventory

### 2.1 Where each control lives

| Surface | Card / modal | Lines | Role |
|---|---|---|---|
| Core parameters | `Critical Configuration` | 1753-1859 | Provider, endpoint, keys, language, model, speakers, VAD, silence, NR, word timestamps |
| Granular parameters | **Settings** modal | 2709-2857 | 24 DSP/decoding knobs + metadata + queue monitor + LLM provider + RunPod |
| Prompt mapping | Settings modal | 2776-2786 | Per-audio suggested prompt → `cfg_initial_prompt` |
| Project routing | Project Journey | 1886-1941 | `project_id`, `canonical_name`, `top_n_references`, guided, async |

`buildConfig()` resolves precedence as `critical* || cfg_* || literal-default`
(`4300-4307`). Because the `critical*` elements are **always populated**, the `cfg_*` twins for
those eight fields are dead — see §3.5.

### 2.2 Field-by-field trace (UI → HTTP → DSP → Whisper)

Legend: **R** = `src/presentation/routers/transcription.py`, **B** = `src/application/dto/helpers.py`,
**U** = `src/application/use_cases/transcribe_audio.py`, **P** = `src/infrastructure/pydub_processor.py`,
**W** = `src/infrastructure/whisper_adapter.py`.

| UI key (template line) | Backend Form field | Match | In params | Actually used | Effective default |
|---|---|---|---|---|---|
| `provider` (4299) | — none — | **NO** | no | client routing only | always sent |
| `language` (4300) | `language` (R:52) | yes | B:42 | U:169 → `LANGUAGE_MAP` → W:42 | `auto` (UI `es-CL` → `es`) |
| `model_size` (4301) | `whisper_model` alias (R:53) | yes | B:43 | U:170 → W:23 | `large-v3` |
| `min_speakers` (4302) | `min_speakers` (R:54) | yes | B:44 | **inert → fixed, §5.1** | 1 |
| `max_speakers` (4303) | `max_speakers` (R:55) | yes | B:45 | **inert → fixed, §5.1** | 2 |
| `vad_threshold` (4304) | `vad_threshold` (R:56) | yes | B:46 | **inert (powerset model)** | 0.25 |
| `remove_silence` (4305) | `remove_silence` (R:63) | yes | B:52 | U:375 → P:27-32, 112-133 | True |
| `noise_reduce` (4306) | `noise_reduce` (R:58) | yes | B:47 | U:370 → P:55-84 | True |
| `word_timestamps` (4307) | `word_timestamps` (R:80) | yes | B:68 | U:565 → W:39; **result discarded** | False |
| `initial_prompt` (4308) | `initial_prompt` (R:75) | yes | B:63 | U:560 → W:33 | UI ships a 300-char domain prompt |
| `beam_size` (4309) | `beam_size` (R:67) | yes | B:55 | U:554 → W:27 | 5 |
| `best_of` (4310) | `best_of` (R:68) | yes | B:56 | U:555 → W:28, **popped when t=0** | 5 |
| `whisper_temp` (4311) | `whisper_temp` (R:69) | yes | B:57 | U:553 → W:26 | 0.0 |
| `silence_thresh` (4312) | `silence_thresh` (R:64) | yes | B:53 | U:376 → P:30, 120 | −45 |
| `min_silence_len` (4313) | `min_silence_len` (R:65) | yes | B:54 | U:377 → P:31, 120 | 250 |
| `reduction_db` (4314) | `reduction_db` (R:59) | yes | B:48 | U:371 → P:74 | 25 |
| `voice_enhance` (4315) | `voice_enhance` (R:60) | yes | B:49 | U:372 → P:86-94 | True |
| `apply_gain` (4316) | `apply_gain` (R:61) | yes | B:50 | U:373 → P:96-103 | True |
| `target_lufs` (4317) | `target_lufs` (R:62) | yes | B:51 | U:374 → P:97-103 | −16.0 |
| `condition_on_previous_text` (4318) | same (R:74) | yes | B:62 | U:559 → W:32 | False (**UI select defaults `true`**) |
| **`temp_inc`** (4319) | real name `temperature_increment_on_fallback` (R:70) | **NO** | only via right name | nowhere — CLI-only in whisper | ignored |
| **`comp_ratio`** (4320) | real name `compression_ratio_threshold` (R:71) | **NO** | only via right name | U:556 → W:29 | ignored (UI value == default, masking it) |
| **`logprob`** (4321) | real name `logprob_threshold` (R:72) | **NO** | only via right name | U:557 → W:30 | ignored (UI value == default, masking it) |
| `no_speech_threshold` (4322) | same (R:73) | yes | B:61 | U:558 → W:31 | 0.6 |
| `length_penalty` (4323) | `length_penalty` (R:76) | yes | B:64 | U:561 → W:34 | 1.0 |
| `patience` (4324) | `patience` (R:77) | yes | B:65 | U:562 → W:35 | None |
| `project_id` (4326) | only on `/guided` (R:293) | **NO** on plain route | no | routing side-effect only | ignored |
| `canonical_name` (4327) | only on `/guided` (R:290) | **NO** on plain route | no | ref-store key on guided | ignored |
| `top_n_references` (4328) | only on `/guided` (R:294) | **NO** on plain route | no | guided:159-160 | ignored |

**Accepted by the server but never sent by the UI:** `suppress_blank` (R:78),
`suppress_tokens` (R:79, parsed at U:126-133), `keep_cache` (R:82, dead — see §3.7),
`skip_diarization` (R:83, works → single segment, U:416-436).

### 2.3 The DSP stage, precisely

`PydubProcessorAdapter.process()` (`pydub_processor.py`) — **no internal defaults**; absent keys
mean pass-through. Order: decode → `_enhance` → `_remove_silence` → export WAV.

| Stage | Implementation | Real semantics |
|---|---|---|
| Noise reduction (P:55-84) | mono downmix → normalise by `2^(8·width−1)` → find the lowest-RMS 0.5 s window → `noisereduce.reduce_noise(prop_decrease=min(reduction_db/40, 1), stationary=False)` → int16 mono | `reduction_db` is a **0–1 duty fraction, not dB**; the `y_noise` argument is **ignored** by `SpectralGateNonStationary`; output is **always mono 16-bit** |
| Voice enhance (P:86-94) | `low_pass_filter(3400).high_pass_filter(300)` + `compress_dynamic_range(-50, 4:1, 5 ms, 200 ms)` | **telephone band-pass 300–3400 Hz** applied *after* NR; 1-pole RC filters run per-sample in Python |
| Gain (P:96-103) | `audio.dBFS` (RMS dBFS) vs `target_lufs`; `gain = max(target − dBFS, 0)` | **boost-only, never attenuates**, and the label says "LUFS" while the measure is RMS dBFS |
| Silence removal (P:112-133) | `detect_nonsilent` + 80 ms pad + `combined += chunk` | **deletes real pauses and shifts the timeline**; no map back to the original recording |

---

## 3. Defects

Severity: **P0** = wrong results / silent data loss, **P1** = unusable control or resource leak,
**P2** = correctness or ergonomics. Items marked **(fixed)** were corrected in this pass — see §5
for the exact change and §5.1 for the two behaviour changes to be aware of.

### 3.1 P0 — `min_speakers` / `max_speakers` / `vad_threshold` are inert **(fixed)**

`pyannote_adapter.py:34-36` sets them as *instance attributes*:

```python
pipeline.segmentation.threshold = vad_threshold
pipeline.min_speakers = min_speakers
pipeline.max_speakers = max_speakers
```

The installed backend is **pyannote.audio 4.0.7**. `SpeakerDiarization.apply()` reads only its own
kwargs (`speaker_diarization.py:574-578`) → `set_num_speakers(None, None, None)` → min 1, max ∞.
`Pipeline.__setattr__` parks unknown names on the instance, and nothing reads them. The
segmentation-3.0 checkpoint is a **powerset** model, so the `binarize(onset=threshold)` call is
skipped entirely (`speaker_diarization.py:599-604`). Net effect: **the three speaker/VAD controls
in `Critical Configuration` do nothing on the local provider.** `diarize_waveform` (`:63-70`)
already does it correctly, which is what makes this a straightforward bug rather than a design gap.

### 3.2 P0 — three Settings controls are discarded by the server **(fixed)**

`temp_inc`, `comp_ratio`, `logprob` match no `Form(...)` declaration. FastAPI silently ignores
undeclared multipart fields — HTTP 200, values thrown away. They are masked today only because
the UI defaults (0.2 / 2.4 / −1) coincide with the server defaults. **Change any of them and
nothing happens.**

Compounding: `temperature_increment_on_fallback` *is* declared and stored, but is never forwarded
(`transcribe_audio.py:549-566`) and does not exist in the programmatic `whisper.transcribe()`
signature of the installed build — it is CLI-only. So that knob is dead at two layers.

### 3.3 P0 — the guided routes silently drop parameters **(fixed)**

| Route | Declared | Silently dropped |
|---|---|---|
| `/transcribe/guided` (R:287-313) | language, model_size, min/max speakers, vad, NR, reduction, voice enhance, gain, LUFS, silence, beam, best_of, temp, condition_on_prev, word_ts | `compression_ratio_threshold`, `logprob_threshold`, `no_speech_threshold`, `length_penalty`, `patience`, `initial_prompt` (overwritten by the reference-derived prompt at `guided_transcribe.py:106`), `suppress_*`, `keep_cache`, `skip_diarization` |
| `/transcribe/guided/async` (R:361-372) | language, model_size, min/max speakers, vad, top_n | **all preprocessing flags**, `beam_size`, `best_of`, `whisper_temp`, `condition_on_previous_text`, `word_timestamps` |

Because `postTranscriptionWithFallback` auto-selects guided **and** async whenever a project is
selected (`3218-3219`), picking a project silently switches the run to server defaults.

### 3.4 P0 — the async route returns a `job_id` that the UI renders as an empty transcript **(fixed)**

`/transcribe/guided/async` responds with `{job_id, canonical_name, status, status_url, stream_url}`
(R:407-413). `transcribeLocal` (`4559-4577`) treats *any* 2xx JSON as a finished transcript, so
`data.segments` is `undefined` → `renderSegments([])` → **"Transcrição concluída — 0 segmentos"**.
A grep for `job_id`/`EventSource`/`status_url` across the template returns nothing: the UI has no
polling or SSE code at all. The endpoints it needs already exist —
`GET /api/transcripts/status/{job_id}` and `GET /api/transcripts/stream/{job_id}`
(`transcripts.py:800-824`).

### 3.5 P1 — eight Settings controls are unreachable from the UI **(fixed)**

`cfg_language`, `cfg_model_size`, `cfg_min_speakers`, `cfg_max_speakers`, `cfg_vad_threshold`,
`cfg_remove_silence`, `cfg_noise_reduce`, `cfg_word_timestamps` are shadowed by their `critical*`
twins (`4300-4307`). Editing them in the modal appears to work — **Save Config** persists them —
but `buildConfig()` never reads them. Only `applyToHiddenFields()` (`5673-5694`) copies a subset
back, and only from the *critical* panel into the *modal*, never the reverse.

### 3.6 P1 — "Voice enhance" band-limits to telephone quality **(fixed)**

`low_pass_filter(3400)` plus `high_pass_filter(300)` is applied **by default** in both the UI and
the server. Whisper transcribes the full 0–8 kHz band and relies on 3.4–8 kHz for fricatives
(`s`, `f`, `z`, `th`) — the phonemes that separate *"sí"* from *"fin"*, and the ones that matter
most in radio/comms forensics.

**Calibration (measured, this revision).** pydub's `low_pass_filter`/`high_pass_filter` are
**single-pole RC filters**, not steep biquads, so the honest description is a *tilt*, not a brick
wall: a 6 kHz tone comes out ~6 dB down and a 7.5 kHz tone ~8 dB down, versus ~0–1 dB with an
8 kHz cutoff. It does not delete the band; it suppresses it by roughly the same margin as a
lossy codec, on top of a 4:1 compressor at a −50 dBFS threshold. The `high_pass_filter(300)`
additionally removes male F0 energy below 300 Hz. The `audio/` project's own guidance is
explicit: *"Do NOT lowpass at 7–8 kHz."*

### 3.7 P1 — audio artifacts accumulate forever

`keep_audio_artifacts` is never a Form field, so `params.get("keep_audio_artifacts", True)` is
always `True` (`transcribe_audio.py:175`), `_cleanup_artifacts` returns immediately (`:654-655`),
and `keep_cache` (`R:82`) is unreachable (`:664-665`). Every run leaves `*_processed.wav`
plus saved WAVs on disk.

### 3.8 P2 — additional correctness gaps

| # | Issue | Status | Evidence |
|---|---|---|---|
| a | **Silence removal shifts the timeline.** Diarization/Whisper timestamps refer to the *compressed* audio; the UI draws waveform regions against the *original* file. For a forensic tool this breaks audio↔transcript alignment. | *Mitigated:* `/api/pinocchio/audio/silence-map` and the Audio Lab's `trim_silence` op return a `kept` timeline map. The in-pipeline `remove_silence` is unchanged. | P:112-133, U:540-548 |
| b | **Digital silence → NaN.** `noisereduce` returns all-NaN; `np.clip(...).astype(np.int16)` is undefined behaviour. | **(fixed)** denoise skipped on silence + `nan_to_num` | P:83 |
| c | **`reduction_db` is unbounded and mislabelled.** Negative values push the mask above 1 → measured +7.6 dB distortion. It is a strength fraction, not dB. | **(fixed)** clamped 0–40, junk-tolerant, and relabelled in the UI and `parameters.py` | P:74 |
| d | **Gain cannot attenuate and has no peak guard.** `max(target − dBFS, 0)`; a −30 dBFS input raised to −16 can clip. | **(fixed)** bidirectional + peak ceiling, opt-out via `allow_attenuation` | P:99 |
| e | **No numeric bounds on most Form fields.** `beam_size=0` → `AssertionError` → 500; `min_silence_len=0` → silent no-op. | **open** (the Audio Lab clamps its own ops) | R:48-84 |
| f | **Integer Form fields reject decimals with a 422.** `type="number"` + `step="1"` still lets a user type `12.5`; `reduction_db`/`silence_thresh`/`min_silence_len` are `int` → whole request rejected. | **open** | R:59,64,65 |
| g | **`word_timestamps` costs decode time and returns nothing.** Forced in the adapter but `result["words"]` is discarded and `SegmentResult` has no word fields. | **open** | W:39-44 |
| h | **`best_of` is a no-op at the shipped default.** Whisper pops it when `temperature == 0`, which is the UI default. | **open** | whisper `transcribe.py:193-198` |
| i | **`condition_on_previous_text` cannot help across turns.** Each diarized turn is a separate `model.transcribe()` call on a fresh temp WAV. | **open** | U:543-566 |
| j | **`provider = pyannote` does not call pyannote.ai.** `/api/pinocchio/transcribe/pyannote` 307-redirects to the local pipeline. | **open** (documented in the UI copy) | `pinocchio.py:113-120` |
| k | **Sample rate is never normalised in-pipeline.** 8 kHz uploads stay 8 kHz; `dBFS`-based gain is not comparable across bit depths. | *Mitigated:* the Audio Lab's `asr_16k` preset resamples to 16 kHz | P:36 |
| l | **`noise_reduce` forces mono.** Stereo channel cues are lost before diarization. | **open** (the Audio Lab exposes explicit `to_mono`/`channel` ops instead) | P:58-59, 83-84 |

---

## 4. Insights

1. **The UI is a thin client over a wide-but-shallow API.** 27 distinct knobs are sent; the server
   declares 29 fields; but only ~19 values reach a DSP or decoder call. The panel's apparent power
   is roughly 2× the pipeline's real power.
2. **Precedence is inverted and invisible.** Two control surfaces edit overlapping state with
   `critical || cfg` resolution, so the *higher-level, less detailed* card wins over the
   *lower-level, more detailed* modal. Users will reasonably expect the opposite.
3. **`Settings` conflates four unrelated domains** — audio DSP, Whisper decoding, LLM provider
   selection, and RunPod transport — in one flat `grid2`. The DSP knobs and the transport knobs
   have nothing to do with each other and different risk profiles.
4. **Several defaults are self-defeating:** `condition_on_previous_text=true` in the UI but
   `False` in the API and ineffectual anyway; `best_of=5` with `temperature=0`;
   `voice_enhance=true` meaning "degrade to telephone bandwidth".
5. **Nothing measures the result.** There is no SNR, no loudness readout, no clipping indicator,
   no A/B comparison of raw vs processed audio — despite the sibling `audio/` service offering
   `/api/analysis/loudness`, `/api/quality/pesq-stoi` and `/api/quality/mos`, which are exactly
   the instruments needed to prove a preprocessing setting helped. `Technical Details` shows the
   response JSON, not audio quality.
6. **The 4-stage progress model is optimistic.** `Upload → Preprocessing → Diarization →
   Transcription` is advanced by *timers*, not by server events (`transcribeLocal`,
   `4559-4577`; `transcribePyannote` steps on a 3.5 s `setInterval`, `4601-4613`). Only the RunPod
   path reports real progress. The SSE progress channel already implemented server-side
   (`/api/transcripts/stream/{job_id}`) is unused.
7. **Very strong bones exist but are not wired:** `buildSegmentAudioBlob` / `encodeWavFromChannels`
   (`3491-3544`) already do full client-side WAV encode/decode, `WaveSurfer` regions are live
   (`3878-3940`), and `torchaudio` is already a runtime dependency of this service
   (`torchaudio_probe_adapter.py`). The audio-lab feature below is additive, not invasive.

---

## 5. Fixes applied in this pass

| # | Fix | Where |
|---|---|---|
| 5.1 | `min_speakers`/`max_speakers`/`num_speakers` now passed as `pipeline(...)` **kwargs** (mirroring the already-correct `diarize_waveform`); inverted bounds are normalised instead of aborting; the meaningless `segmentation.threshold` mutation is replaced by a debug-level explanation so `vad_threshold` is no longer *silently* ignored | `src/infrastructure/pyannote_adapter.py` |
| 5.2 | `buildConfig()` now emits `temperature_increment_on_fallback`, `compression_ratio_threshold`, `logprob_threshold`; the old short names remain as *aliases* in `applySuggestionObject` so previously saved suggestion payloads keep working | `templates/pinocchio-en.html` |
| 5.3 | Guided and guided-async routes now declare the full parameter set (`enhance_highpass_hz`, `enhance_lowpass_hz`, `allow_attenuation`, `compression_ratio_threshold`, `logprob_threshold`, `no_speech_threshold`, `length_penalty`, `patience`, `suppress_blank`, `suppress_tokens`, `initial_prompt`), and `ReferenceGuidedTranscribeUseCase` forwards the optional decoding controls to the ASR adapter | `src/presentation/routers/transcription.py`, `src/application/use_cases/guided_transcribe.py` |
| 5.4 | The UI detects a `job_id` response, polls `GET /api/transcripts/status/{job_id}` on a 2 s cadence (2 h ceiling, 5-error tolerance), maps `stage`/`progress` onto the real progress bar, and only then renders the transcript | `templates/pinocchio-en.html` |
| 5.5 | New **Audio Lab** panel in the File & Execution column (see §6) backed by a new in-process router | template + `src/presentation/routers/audio_lab.py` |
| 5.6 | Legacy processor safety: `reduction_db` clamped to 0–40 and junk-tolerant, `nan_to_num` on the denoiser output, the denoise stage skipped entirely on digital silence, a **peak-guarded and bidirectional** gain stage (was boost-only), and **configurable band-pass edges** (`enhance_highpass_hz` / `enhance_lowpass_hz`) that now **default to the speech-safe 60 / 8000 Hz** | `src/infrastructure/pydub_processor.py` |
| 5.7 | Settings modal surfaces the previously unreachable controls: `suppress_blank`, `suppress_tokens`, `keep_cache`, `skip_diarization`, plus the band-pass edges and `allow_attenuation` | template |
| 5.8 | **Dead Settings controls fixed.** `syncCriticalFromCfg()` pushes the eight overlapping modal fields back into the Critical Configuration card on Save *and* Load, so the two surfaces agree instead of one silently winning | template |

### 5.1 Behaviour changes to be aware of

Two changes are not purely additive. Both are deliberate and reversible:

1. **`voice_enhance` now band-passes at 60 / 8000 Hz by default** instead of 300 / 3400 Hz.
   Callers that want the old response must pass `enhance_highpass_hz=300&enhance_lowpass_hz=3400`.
   Rationale in §3.6; the change is what makes the UI's band controls meaningful.
2. **Loudness normalisation can now attenuate**, and it reserves 1 dB of headroom when boosting.
   The previous behaviour was `max(target − dBFS, 0)`, i.e. boost-only and clipping-prone.
   Pass `allow_attenuation=false` for the legacy semantics.

Everything else is additive: new optional parameters default to the previous behaviour, and
`PydubProcessorAdapter.process()` remains a pass-through when handed an empty params dict.

---

## 6. Audio Lab — manipulation features adopted from `audio/`

The sibling `audio/` project (FastAPI on `:8777` + an OpenAPI-driven MCP bridge on `:8765`)
exposes 40 endpoints. Probing it produced a clear relevance verdict for *transcription*:

**Genuinely useful:** resample (Whisper is 16 kHz mono-native), high-pass at 60–100 Hz (kills DC,
rumble and handling noise that corrupt VAD), a real STFT denoiser, a Schroeder-RT60 dereverb,
gain/loudness normalisation, speech separation (the only overlap remedy), and SQUIM-based
PESQ/STOI/MOS as the *decision instruments*.

**Neutral or harmful for ASR:** pre/de-emphasis, speed, time-stretch, pitch-shift, `add-noise`,
`convolve`/`ir-convolve`, dither, overdrive, contrast, flanger, phaser, and the *music* 4-stem
`/api/separate` (whose `low` default runs randomly-initialised weights and always emits 44.1 kHz).
Analysis endpoints (spectrogram/MFCC/SSL) are diagnostics, not preprocessing.

Also confirmed: **CORS is not a blocker** (`allow_origins=["*"]`, Starlette echoes the Origin),
but the service is single-worker with CPU-bound `async` handlers, every DSP call returns base64
WAV (~33 % inflation), and **no endpoint accepts or returns a `session_id` for chaining** — so the
existing UI cannot chain it. That is why the lab is implemented **in-process** in the
transcription service instead of proxied.

### 6.1 Implementation

* `src/infrastructure/audio_dsp.py` — dependency-light DSP core (numpy + scipy, WAV via the
  stdlib `wave` module), so it is unit-testable without torch:
  * I/O: `load_audio`, `save_wav` (16/32-bit PCM, 8/16/24/32-bit input, mono→8 channels),
    polyphase resampling, NaN/Inf sanitisation at every boundary
  * Filters: RBJ biquad high-pass / low-pass / band-pass / notch
  * `spectral_denoise` — STFT magnitude gating with a noise profile estimated from the
    lowest-energy 10 % of frames, Hann window + overlap-add, with a RMS-drift guard
  * `dereverb` — decay-tracking peak envelope; subtracts only the *excess* over the present
    frame, so stationary speech is untouched (measured: −0.01 dB on steady speech, −0.8 to
    −2.2 dB on decay tails, monotonic in `amount`)
  * `normalize` — peak-guarded gain toward a target dBFS, bidirectional
  * `measure` — duration, sample rate, channels, peak/RMS dBFS, crest factor, DC offset,
    clipping %, silence ratio, noise floor, SNR estimate, **true ITU-R BS.1770-4 integrated
    loudness** (K-weighting + absolute/relative gating, verified within ~0.3 dB of reference),
    spectral centroid, 85 % rolloff, and the 3.4–8 kHz energy share, plus actionable tips
  * `detect_silence` / `trim_silence` — silence regions **with original-timeline mapping**
    (fixes §3.8a); `trim_silence` returns `kept` triples `[out_start, in_start, duration]`
  * `process_chain` — ordered op execution with per-step frame/sample-rate tracing, unknown-op
    rejection, and clamping of every numeric parameter
* `src/presentation/routers/audio_lab.py` — `GET /api/pinocchio/audio/capabilities`,
  `POST /analyze`, `POST /silence-map`, `POST /suggest-chain`, `POST /process`.
  `process` returns WAV bytes plus an `X-Audio-Lab-Report` header (URL-safe base64 JSON, with
  the reporting headers added to `Access-Control-Expose-Headers`), and can persist into
  `data/audio` with `save=true`. Uploads are written to a private temp dir and
  server-side `audio_path` inputs are **copied first**, because
  `AudioFileAdapter.convert_to_wav` deletes its input.
* UI: an **Audio Lab** card inside the File & Execution column — Analyze, Suggest chain,
  Process, Apply to session, Download WAV, Transcribe processed, Revert — with a quality
  report rendered as chips plus a raw-JSON panel. A small `window.__pinocchioBridge` exposes
  the current file, the waveform setter and the transcribe entry point so the panel does not
  reach into the main script's lexical scope.

### 6.2 Verification

* `tests/unit/test_audio_dsp.py` (66 tests) — I/O round-trips, filter responses, loudness
  reference, STFT/ISTFT reconstruction to 1e-4, denoiser NaN-safety, dereverb selectivity,
  silence detection and timeline maps, chain execution, hostile-input clamping.
* `tests/unit/test_audio_lab_router.py` (32 tests) — every route, validation errors, container
  conversion, `save`, determinism, and the "do not destroy the caller's file" guarantee.
* End-to-end through the composed app: analyze → silence-map → process (preset) → process
  (explicit chain + trim) all return 200 with coherent reports and decodable WAV output.

---

## 7. Prioritised improvement backlog

**P0 — correctness**
1. ✅ `min_speakers`/`max_speakers` kwargs *(done)*.
2. ✅ UI field names / guided params / async `job_id` *(done)*.
3. **Decide `vad_threshold`'s fate.** With the powerset segmentation model it has no effect.
   Either expose pyannote's real VAD knobs (`min_duration_off`, `min_duration_on`) or remove the
   control. Do not leave a knob that lies.
4. **Adopt `trim_silence` + timeline map as the default** instead of destructive silence removal,
   or at minimum record the removed-region map in the transcript so audio↔text alignment survives.

**P1 — make the UI honest**
5. **Single source of truth for configuration.** The eight overlapping controls are now synced in
   both directions (§5.8), but the cleaner end state is one schema-driven form with one
   precedence rule, rendered from `GET /api/diarization/parameters` (which already exists, now
   carries the audio-lab section, and is still unused by this template).
6. **Align the remaining defaults:** `best_of` should only be sent when `temp > 0` (it is popped
   otherwise), and `condition_on_previous_text` should agree between the UI select and the API
   default. `voice_enhance` band edges are done (§5.1).
7. **Make `keep_audio_artifacts` a real parameter** so the cleanup path is reachable and disk
   usage is bounded.
8. **Wire the SSE progress channel** (`/api/transcripts/stream/{job_id}`) so the local and
   guided-async paths can report *real* progress instead of polling. The job tracking and the
   endpoint already exist; §5.4 currently polls the status route on a 2 s cadence.

**P2 — capability**
9. **Surface measurement in the UI**: SNR, loudness, clipping and a raw-vs-processed A/B using
   the Audio Lab and, optionally, `audio/`'s `/api/quality/pesq-stoi` for an objective verdict.
10. **`suppress_tokens` presets** for Chilean-Spanish filler/vocabulary priming.
11. **Return `words`** when `word_timestamps` is on, and store them on `SegmentResult`.
12. **Post-run suggestion loop**: `applySuggestionObject` (`4433-4499`) already applies server
    suggestions to the DOM — feed it Audio Lab metrics so the tool can propose "denoise 0.6,
    high-pass 80 Hz" for a noisy recording.
13. **Batch/A-B runner**: transcribe the same file with 2–3 preprocessing presets and compare
    `avg_logprob` / `no_speech_prob` distributions, which `renderSavedTable` already computes
    (`5044`, `4873-4874`).

---

## 8. Verification notes

`python -m pytest tests/unit` → **588 passed** on this revision (up from 397; 191 new tests).

| New test file | Covers |
|---|---|
| `tests/unit/test_audio_dsp.py` | DSP core: I/O, filters, resampling, loudness, STFT round-trip, denoise/dereverb behaviour, silence maps, chain execution, hostile inputs |
| `tests/unit/test_audio_lab_router.py` | Every Audio Lab route, validation errors, container conversion, `save`, determinism, non-destructive `audio_path` handling |
| `tests/unit/test_audio_processor_and_diarizer.py` | `min_speakers`/`max_speakers` forwarded as kwargs (and *not* as instance attributes), gain attenuation + peak ceiling, strength clamping, band-pass edges, digital-silence safety |
| `tests/unit/test_guided_param_forwarding.py` | Guided pipeline forwards preprocessing and optional decoding controls; every transcribe route declares the fields the UI sends |
| `tests/unit/test_pinocchio_file_execution_ui.py` | Template invariants: exact server field names, absence of the three bogus keys, alias preservation, job polling, critical↔modal sync, Audio Lab wiring and speech-safe defaults |
| `tests/unit/test_template_escaping.py` (existing) | Also `node --check`s every inline script block, so a broken template edit fails in CI rather than in the browser |

The template was additionally syntax-checked block-by-block with `node --check` and exercised
end-to-end against the composed FastAPI app (analyze → silence-map → process → process+trim).

The `audio/` findings in §6 are from live probes against `:8777` / `:8765`; notable upstream
defects found while doing so, for the `audio/` maintainers: `/api/separate`'s default
`model_size="low"` runs a **randomly-initialised** `hdemucs_low`; `/api/analysis/loudness` 500s
on clips < 0.4 s and on digital silence; `/api/vad` returns a front-trimmed waveform array rather
than segments; `/api/analysis/mfcc`'s `to_db` is dead; 22 routes return non-JSON bare 500s;
`dynamic_server`'s `/status` health-checks port 8000 instead of 8777; and no DSP endpoint accepts
or returns a chaining `session_id`.
