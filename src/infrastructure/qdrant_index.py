"""Qdrant transcript index — implements TranscriptIndexPort."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, PointStruct, VectorParams

from src.domain.entities.transcript import Transcript

logger = logging.getLogger(__name__)

COLLECTION = "transcription_transcripts"
VECTOR_DIM = 384  # all-MiniLM-L6-v2 output dimension

# Path to the speaker index produced by scripts/generate_speaker_index_v3.py
_SPEAKER_INDEX_PATH = Path(__file__).resolve().parents[2] / "data" / "speaker_index.json"


class QdrantTranscriptIndex:
    """Index and search transcript segments in Qdrant. Implements TranscriptIndexPort."""

    def __init__(
        self,
        url: str = "http://localhost:6333",
        api_key: str | None = None,
        speaker_index_path: Path | str | None = None,
    ):
        normalized_url = self._normalize_qdrant_url(url)
        normalized_key = self._normalize_qdrant_api_key(api_key)
        self._client = QdrantClient(url=normalized_url, api_key=normalized_key or None)
        self._encoder = None  # lazy-loaded
        self._ensure_collection()

        # Build speaker lookup tables from speaker_index.json
        # _spk_by_seg:   (transcript_id, segment_index) -> speaker_id
        # _spk_by_label: (transcript_id, speaker_label_lower) -> speaker_id
        index_path = Path(speaker_index_path) if speaker_index_path else _SPEAKER_INDEX_PATH
        self._spk_by_seg: dict[tuple[str, int], str] = {}
        self._spk_by_label: dict[tuple[str, str], str] = {}
        self._load_speaker_index(index_path)

    def _load_speaker_index(self, path: Path) -> None:
        """Parse speaker_index.json and populate the two lookup dicts.

        For each ``SPK-…`` key we look at every occurrence entry:
        - If the entry has ``segment_indices`` we map each (transcript_id, idx) → spk_id.
        - In all cases we map (transcript_id, speaker_label_lower) → spk_id so that
          fallback label matching still benefits from the index.
        """
        if not path.exists():
            logger.warning("[qdrant] speaker_index.json not found at %s — speaker IDs will rely on participant data only", path)
            return

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[qdrant] failed to load speaker_index.json: %s", exc)
            return

        mapped: dict = data.get("mapped_speakers", {})
        for spk_id, speaker_meta in mapped.items():
            # Support both v2 (list of appearances) and v3 (dict with appearances key)
            if isinstance(speaker_meta, list):
                occurrences = speaker_meta
            else:
                occurrences = speaker_meta.get("appearances", [])
                
            for occ in occurrences:
                tid = occ.get("transcript_id", "")
                if not tid:
                    continue

                # Exact segment-index mapping (highest priority)
                seg_indices = occ.get("segment_indices")
                if seg_indices:
                    for idx in seg_indices:
                        self._spk_by_seg[(tid, int(idx))] = spk_id

                # Label-based fallback: use speaker_label (participant) or speaker (segment)
                label = (occ.get("speaker_label") or occ.get("speaker") or "").strip().lower()
                if label:
                    # Only set if not already present (first match wins, preserving priority order)
                    self._spk_by_label.setdefault((tid, label), spk_id)

        logger.info(
            "[qdrant] loaded speaker_index: %d segment-exact mappings, %d label mappings",
            len(self._spk_by_seg),
            len(self._spk_by_label),
        )

    @staticmethod
    def _normalize_qdrant_url(raw_url: str) -> str:
        value = (raw_url or "").strip()
        if not value:
            return ""

        parsed = urlparse(value if "://" in value else f"https://{value}")
        if parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return value

    @staticmethod
    def _normalize_qdrant_api_key(raw_key: str | None) -> str:
        key = (raw_key or "").strip()
        if not key:
            return ""

        if "|" not in key:
            return key

        parts = [p.strip() for p in key.split("|") if p.strip()]
        if not parts:
            return key
        return max(parts, key=len)

    def _ensure_collection(self, collection_name: str = COLLECTION) -> None:
        collections = [c.name for c in self._client.get_collections().collections]
        if collection_name not in collections:
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            logger.info("[qdrant] created collection %s", collection_name)
        # Ensure payload indexes for commonly filtered fields
        for field_name in ("transcript_id", "speaker", "case_id", "narrative_id",
                           "tags", "forensic_cluster_ids", "key_finding_ids"):
            try:
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
            except Exception:
                logger.debug("[qdrant] payload index %s.%s may already exist", collection_name, field_name)

    def _get_encoder(self):
        """Lazy-load the sentence transformer on first use."""
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("[qdrant] loaded embedding model all-MiniLM-L6-v2")
        return self._encoder

    def _make_point_id(self, transcript_id: str, segment_index: int) -> str:
        """Deterministic UUID-compatible hex id from transcript + segment."""
        raw = f"{transcript_id}:{segment_index}"
        return hashlib.md5(raw.encode()).hexdigest()  # noqa: S324

    async def counts_by_transcript(
        self, collection_name: str = COLLECTION, *, timeout: float = 15.0
    ) -> dict[str, int]:
        """Return ``{transcript_id: point_count}`` for a collection.

        Replaces the old N+1 pattern (one synchronous ``count()`` per transcript
        on the event loop) with a single paginated ``scroll`` executed off the
        event loop. Returns an empty mapping when the collection is missing or
        unreachable, so listing transcripts never fails because of the vector
        store.
        """

        def _scan() -> dict[str, int]:
            collections = [c.name for c in self._client.get_collections().collections]
            if collection_name not in collections:
                return {}
            counts: dict[str, int] = {}
            next_offset = None
            while True:
                points, next_offset = self._client.scroll(
                    collection_name=collection_name,
                    with_payload=["transcript_id"],
                    with_vectors=False,
                    limit=1000,
                    offset=next_offset,
                )
                for point in points:
                    tid = (point.payload or {}).get("transcript_id")
                    if tid:
                        counts[tid] = counts.get(tid, 0) + 1
                if next_offset is None:
                    break
            return counts

        try:
            return await asyncio.wait_for(asyncio.to_thread(_scan), timeout=timeout)
        except Exception as e:  # noqa: BLE001 - never fail the listing on vector-store trouble
            logger.warning("[qdrant] counts_by_transcript failed for %s: %s", collection_name, e)
            return {}

    async def index(self, transcript: Transcript, collection_name: str = COLLECTION) -> int:
        """Index all segments of a transcript. Returns number of points upserted."""
        if not transcript.segments:
            return 0

        self._ensure_collection(collection_name)
        encoder = await asyncio.to_thread(self._get_encoder)

        texts = [seg.text for seg in transcript.segments]
        embeddings = await asyncio.to_thread(encoder.encode, texts)

        # Compute local_time per segment if recording_datetime is available
        recording_dt = transcript.recording_datetime or (
            transcript.metadata or {}
        ).get("recording_datetime", "")
        base_dt = None
        if recording_dt:
            try:
                base_dt = datetime.fromisoformat(recording_dt)
            except (ValueError, TypeError):
                pass

        points = []
        for seg, emb in zip(transcript.segments, embeddings, strict=False):
            point_id = self._make_point_id(transcript.transcript_id, seg.index)

            # ------------------------------------------------------------------
            # Resolve speaker_id — three-tier priority:
            #   1. Exact (transcript_id, segment_index) hit from speaker_index.json
            #   2. Label hit from speaker_index.json  (generic label → SPK-... key)
            #   3. Transcript's own participants array (legacy fallback)
            # ------------------------------------------------------------------
            tid = transcript.transcript_id
            seg_speaker = (seg.speaker.label or "").strip().lower()

            speaker_id: str | None = (
                # Priority 1 — segment-index exact match
                self._spk_by_seg.get((tid, seg.index))
                # Priority 2 — label match from index
                or (self._spk_by_label.get((tid, seg_speaker)) if seg_speaker else None)
            )

            if speaker_id is None:
                # Priority 3 — scan transcript's own participants (unchanged legacy logic)
                participants = getattr(transcript, "participants", []) or []
                for p in participants:
                    p_role = (p.get("role") or "").strip().lower()
                    p_label = (p.get("speaker_label") or "").strip().lower()
                    if seg_speaker and (seg_speaker == p_role or seg_speaker == p_label):
                        speaker_id = p.get("speaker_id")
                        break

            payload = {
                "transcript_id": transcript.transcript_id,
                "segment_id": f"{transcript.transcript_id}.seg-{seg.index}",
                "segment_index": seg.index,
                "speaker": seg.speaker.label,
                "speaker_id": speaker_id,
                "start": seg.start,
                "end": seg.end,
                "text": seg.text,
                "source_file": transcript.source_file,
                "language": transcript.language,
                "reviewed": getattr(seg, "reviewed", False),
                "correction_note": getattr(seg, "correction_note", ""),
                "backchannel_events": getattr(seg, "backchannel_events", ""),
            }
            if base_dt:
                local_dt = base_dt + timedelta(seconds=seg.start)
                payload["local_time"] = local_dt.isoformat()

            # ------------------------------------------------------------------
            # NEW: parent metadata enrichment
            # ------------------------------------------------------------------
            payload["case_id"] = getattr(transcript, "case_id", None)
            payload["narrative_id"] = getattr(transcript, "narrative_id", None)
            payload["title"] = getattr(transcript, "title", None)
            payload["location"] = getattr(transcript, "location", None)
            payload["recording_datetime"] = (
                str(transcript.recording_datetime)
                if transcript.recording_datetime
                else None
            )
            payload["chronological_order"] = getattr(transcript, "chronological_order", None)
            payload["prior_stage"] = getattr(transcript, "prior_stage", None)
            payload["next_stage"] = getattr(transcript, "next_stage", None)
            payload["tags"] = getattr(transcript, "tags", [])
            payload["violations_cited"] = getattr(transcript, "violations_cited", [])
            payload["participants"] = getattr(transcript, "participants", [])

            # Forensic clusters: store IDs of clusters that contain this segment
            forensic_clusters = getattr(transcript, "forensic_clusters", None) or {}
            cluster_ids = []
            for cid, cluster in forensic_clusters.items():
                segs = cluster.get("segments", [])
                if isinstance(segs, list):
                    for r in segs:
                        if isinstance(r, int) and seg.index == r:
                            cluster_ids.append(cid)
                            break
                        if isinstance(r, str) and "-" in r:
                            try:
                                low, high = map(int, r.split("-"))
                                if low <= seg.index <= high:
                                    cluster_ids.append(cid)
                                    break
                            except ValueError:
                                pass
            payload["forensic_cluster_ids"] = cluster_ids

            # Key evidentiary findings: store finding IDs that cite this segment
            findings = getattr(transcript, "key_evidentiary_findings", None) or []
            finding_ids = []
            for f in findings:
                segs = f.get("segments", [])
                if seg.index in segs:   # assumes segments is a list of ints
                    finding_ids.append(f.get("id"))
            payload["key_finding_ids"] = finding_ids

            points.append(
                PointStruct(
                    id=point_id,
                    vector=emb.tolist(),
                    payload=payload,
                )
            )

        await asyncio.to_thread(
            self._client.upsert,
            collection_name=collection_name,
            points=points,
        )

        logger.info(
            "[qdrant] indexed %d segments for transcript=%s in collection=%s",
            len(points),
            transcript.transcript_id,
            collection_name,
        )
        return len(points)

    async def search(self, query: str, *, limit: int = 5, collection_name: str = COLLECTION) -> list[dict]:
        """Semantic search across all transcript segments."""
        encoder = await asyncio.to_thread(self._get_encoder)
        query_vector = await asyncio.to_thread(encoder.encode, query)

        self._ensure_collection(collection_name)
        results = await asyncio.to_thread(
            self._client.query_points,
            collection_name=collection_name,
            query=query_vector.tolist(),
            limit=limit,
        )

        return [
            {
                "transcript_id": hit.payload["transcript_id"],
                "segment_id": hit.payload.get("segment_id"),
                "segment_index": hit.payload["segment_index"],
                "speaker": hit.payload["speaker"],
                "speaker_id": hit.payload.get("speaker_id"),
                "start": hit.payload["start"],
                "end": hit.payload["end"],
                "text": hit.payload["text"],
                "source_file": hit.payload.get("source_file", ""),
                "language": hit.payload.get("language", ""),
                "score": hit.score,
                "reviewed": hit.payload.get("reviewed", False),
                "correction_note": hit.payload.get("correction_note", ""),
                "backchannel_events": hit.payload.get("backchannel_events", ""),
                "case_id": hit.payload.get("case_id"),
                "narrative_id": hit.payload.get("narrative_id"),
                "location": hit.payload.get("location"),
                "prior_stage": hit.payload.get("prior_stage"),
                "next_stage": hit.payload.get("next_stage"),
                "tags": hit.payload.get("tags"),
                "violations_cited": hit.payload.get("violations_cited"),
                "forensic_cluster_ids": hit.payload.get("forensic_cluster_ids"),
            }
            for hit in results.points
        ]

    async def delete(self, transcript_id: str, collection_name: str = COLLECTION) -> None:
        """Remove all points for a given transcript."""
        # pyrefly: ignore [missing-import]
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self._ensure_collection(collection_name)
        await asyncio.to_thread(
            self._client.delete,
            collection_name=collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="transcript_id",
                        match=MatchValue(value=transcript_id),
                    )
                ]
            ),
        )
        logger.info(
            "[qdrant] deleted vectors for transcript=%s from collection=%s",
            transcript_id,
            collection_name,
        )