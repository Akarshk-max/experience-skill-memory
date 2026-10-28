"""Assign Episode v2 records and create one candidate skill at the threshold.

`SkillGenerator.generate(bucket, episodes)` is the only model boundary. This
prototype ships `FakeSkillGenerator` for tests. No provider client is constructed.
"""

from __future__ import annotations

import copy
from typing import Any, Protocol

from bucket_tools import BucketTools
from models import (
    DEFAULT_ACTION_THRESHOLD,
    DEFAULT_TASK_THRESHOLD,
    DEFAULT_TRACE_THRESHOLD,
    SystemClock,
    episode_body,
    skill_id_for,
    validate_episode,
)
from skill_draft import FakeSkillGenerator
from skill_tools import SkillTools
from storage.interfaces import StoreError
from storage.weaviate_index import DisabledSkillVectorIndex


class SkillGenerator(Protocol):
    """Provider-independent skill draft boundary. Implementations must not be assumed to be a live model."""

    def generate(self, bucket: dict[str, Any], episodes: list[dict[str, Any]]) -> Any: ...


class SkillCreationService:
    def __init__(
        self,
        store: Any,
        *,
        threshold: int = DEFAULT_TRACE_THRESHOLD,
        task_threshold: float = DEFAULT_TASK_THRESHOLD,
        action_threshold: float = DEFAULT_ACTION_THRESHOLD,
        generator: Any = None,
        clock: Any = None,
        vector_index: Any = None,
    ) -> None:
        if threshold < 1:
            raise ValueError("threshold must be at least 1")
        self.store = store
        self.generator = generator
        self.clock = clock or SystemClock()
        self.vector_index = vector_index or DisabledSkillVectorIndex()
        self.buckets = BucketTools(
            store,
            self.clock,
            task_threshold=task_threshold,
            action_threshold=action_threshold,
            trace_threshold=threshold,
        )
        self.skills = SkillTools(store, self.clock)

    def ingest(self, episode: dict[str, Any]) -> dict[str, Any]:
        prepared = self._prepare(episode)
        if not prepared["ok"] or prepared.get("already"):
            return prepared["result"] if prepared.get("already") else prepared
        match = self.buckets.search_buckets(prepared["episode"])
        if not match["ok"]:
            return match
        return self._commit(
            prepared["episode"],
            match["decision"],
            match["selected_bucket_id"],
            match,
        )

    def ingest_proposal(self, episode: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
        prepared = self._prepare(episode)
        if not prepared["ok"] or prepared.get("already"):
            return prepared["result"] if prepared.get("already") else prepared
        review = self.buckets.review_proposal(prepared["episode"], proposal)
        if not review["ok"]:
            review["episode_stored"] = True
            review["bucket_written"] = False
            return review
        return self._commit(
            prepared["episode"],
            review["match"]["decision"],
            review["match"]["selected_bucket_id"],
            review["match"],
        )

    def generate_for_bucket(self, bucket_id: str) -> dict[str, Any]:
        bucket = self.store.get_bucket(bucket_id)
        if bucket is None:
            return {"ok": False, "error": "unknown_bucket", "message": f"Unknown bucket {bucket_id}."}
        expected = skill_id_for(bucket_id)
        existing = self.store.get_skill(expected)
        if existing is not None:
            self._mark_created(bucket, expected)
            return {
                "ok": True,
                "skill": existing,
                "idempotent": True,
                "vector_index": self._safe_index(existing),
            }
        if bucket["status"] not in ("ready_for_generation", "generation_failed"):
            return {
                "ok": False,
                "error": "not_ready",
                "message": "The bucket has not reached its distinct-trace threshold.",
            }
        if self.generator is None:
            return {
                "ok": False,
                "error": "generator_not_configured",
                "message": "No skill generator is configured.",
            }
        evidence = self.buckets.list_bucket_evidence(bucket_id)
        if not evidence["ok"]:
            self._mark_failed(bucket, evidence["message"])
            return evidence
        try:
            draft = self.generator.generate(bucket, evidence["episodes"])
        except Exception as exc:
            self._mark_failed(bucket, f"generator_error: {exc}")
            return {"ok": False, "error": "generator_error", "message": str(exc)}
        assembled = self.skills.assemble(draft, self.store.get_bucket(bucket_id), evidence["episodes"])
        if not assembled["ok"]:
            self._mark_failed(bucket, "; ".join(assembled["details"])[:500])
            return assembled
        skill = assembled["skill"]
        try:
            self.store.insert_skill(skill)
        except StoreError as exc:
            if exc.code != "duplicate_skill":
                self._mark_failed(bucket, exc.message)
                return {"ok": False, "error": exc.code, "message": exc.message}
            skill = self.store.get_skill(expected)
        self._mark_created(bucket, skill["skill_id"])
        return {
            "ok": True,
            "skill": self.store.get_skill(skill["skill_id"]),
            "idempotent": False,
            "vector_index": self._safe_index(skill),
        }

    def _prepare(self, episode: dict[str, Any]) -> dict[str, Any]:
        errors = validate_episode(episode)
        if errors:
            return {
                "ok": False,
                "error": "invalid_episode",
                "message": "Episode v2 validation failed.",
                "details": errors,
                "episode_stored": False,
                "bucket_written": False,
            }
        episode = copy.deepcopy(episode)
        existing = self.store.get_episode(episode["episode_id"])
        if existing is not None:
            if episode_body(existing) != episode_body(episode):
                return {
                    "ok": False,
                    "error": "episode_identity_conflict",
                    "message": "episode_id already stores different evidence.",
                    "episode_stored": True,
                    "bucket_written": False,
                }
            if existing.get("bucket_id"):
                bucket = self.store.get_bucket(existing["bucket_id"])
                skill = None
                if bucket and bucket.get("skill_id"):
                    skill = self.store.get_skill(bucket["skill_id"])
                reached = bool(bucket and bucket["distinct_trace_count"] >= bucket["threshold"])
                return {
                    "ok": True,
                    "already": True,
                    "result": {
                        "ok": True,
                        "decision": "already_assigned",
                        "bucket": bucket,
                        "skill": skill,
                        "episode_stored": True,
                        "bucket_written": False,
                        "threshold_reached": reached,
                        "generation": {"ok": True, "attempted": False, "reason": "already_assigned", "skill": skill},
                        "vector_index": None,
                    },
                }
        else:
            episode["bucket_id"] = None
            self.store.put_episode(episode)
        return {"ok": True, "episode": self.store.get_episode(episode["episode_id"])}

    def _commit(
        self,
        episode: dict[str, Any],
        decision: str,
        selected: str | None,
        match: dict[str, Any],
    ) -> dict[str, Any]:
        if decision == "ambiguous":
            return {
                "ok": True,
                "decision": "ambiguous",
                "bucket": None,
                "skill": None,
                "episode_stored": True,
                "bucket_written": False,
                "threshold_reached": False,
                "candidates": match["candidates"],
                "generation": None,
                "vector_index": None,
            }
        if decision == "create_new":
            written = self.buckets.create_bucket(episode)
        elif decision == "assign_existing" and selected:
            written = self.buckets.add_episode_to_bucket(selected, episode["episode_id"])
        else:
            return {"ok": False, "error": "unsupported_decision", "message": decision}
        if not written["ok"]:
            written["episode_stored"] = True
            written["bucket_written"] = False
            return written
        generation = self._maybe_generate(written["bucket"])
        bucket = self.store.get_bucket(written["bucket"]["bucket_id"])
        skill = generation.get("skill") if generation.get("ok") else None
        return {
            "ok": True,
            "decision": decision,
            "bucket": bucket,
            "skill": skill,
            "episode_stored": True,
            "bucket_written": True,
            "threshold_reached": bucket["distinct_trace_count"] >= bucket["threshold"],
            "candidates": match.get("candidates"),
            "generation": generation,
            "vector_index": generation.get("vector_index"),
            "skill_created": bucket["status"] == "skill_created",
        }

    def _maybe_generate(self, bucket: dict[str, Any]) -> dict[str, Any]:
        bucket = self.store.get_bucket(bucket["bucket_id"])
        if bucket["status"] == "skill_created":
            skill = self.store.get_skill(bucket["skill_id"]) if bucket.get("skill_id") else None
            return {"ok": True, "attempted": False, "reason": "already_created", "skill": skill}
        if bucket["status"] not in ("ready_for_generation", "generation_failed"):
            return {"ok": True, "attempted": False, "reason": "below_threshold", "skill": None}
        if self.generator is None:
            return {"ok": True, "attempted": False, "reason": "generator_not_configured", "skill": None}
        result = self.generate_for_bucket(bucket["bucket_id"])
        result["attempted"] = True
        return result

    def _mark_failed(self, bucket: dict[str, Any], message: str) -> None:
        current = self.store.get_bucket(bucket["bucket_id"]) or bucket
        current["status"] = "generation_failed"
        current["skill_id"] = None
        current["generation_error"] = message[:500]
        current["updated_at"] = self.clock.now()
        self.store.replace_bucket(current)

    def _mark_created(self, bucket: dict[str, Any], skill_id: str) -> None:
        current = self.store.get_bucket(bucket["bucket_id"]) or bucket
        current["status"] = "skill_created"
        current["skill_id"] = skill_id
        current["generation_error"] = None
        current["updated_at"] = self.clock.now()
        self.store.replace_bucket(current)

    def _safe_index(self, skill: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.vector_index.index_skill(skill)
        except Exception as exc:
            return {"status": "error", "reason": str(exc), "written": False}
