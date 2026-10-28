"""Trusted bucket tools. Counts, status, and writes stay in this module."""

from __future__ import annotations

import copy
from typing import Any

from bucket_assignment import evaluate_bucket, match_episode
from models import (
    BUCKET_SCHEMA_VERSION,
    allocate_bucket_id,
    environment_signature,
    episode_ref,
    validate_episode,
)
from schema_validate import load_schema, validate_instance
from storage.interfaces import StoreError

BUCKET_SCHEMA = load_schema("bucket.schema.json")
DECISION_SCHEMA = load_schema("assignment_decision.schema.json")


class BucketTools:
    def __init__(
        self,
        store: Any,
        clock: Any,
        *,
        task_threshold: float,
        action_threshold: float,
        trace_threshold: int,
    ) -> None:
        self.store = store
        self.clock = clock
        self.task_threshold = task_threshold
        self.action_threshold = action_threshold
        self.trace_threshold = trace_threshold

    def search_buckets(self, episode: dict[str, Any]) -> dict[str, Any]:
        errors = validate_episode(episode)
        if errors:
            return _fail("invalid_episode", "Episode v2 validation failed.", details=errors)
        match = match_episode(
            episode,
            self.store.list_buckets(),
            task_threshold=self.task_threshold,
            action_threshold=self.action_threshold,
        )
        return {"ok": True, **match}

    def create_bucket(self, episode: dict[str, Any]) -> dict[str, Any]:
        errors = validate_episode(episode)
        if errors:
            return _fail("invalid_episode", "Episode v2 validation failed.", details=errors)
        if self.store.get_episode(episode["episode_id"]) is None:
            return _fail("unknown_episode", "Store the episode before creating a bucket.")
        match = match_episode(
            episode,
            self.store.list_buckets(),
            task_threshold=self.task_threshold,
            action_threshold=self.action_threshold,
        )
        if match["decision"] == "assign_existing":
            return _fail(
                "suitable_bucket_exists",
                "An open bucket already matches this episode.",
                bucket_id=match["selected_bucket_id"],
            )
        if match["decision"] == "ambiguous":
            return _fail(
                "ambiguous_candidates",
                "More than one bucket matches. No bucket was created.",
                candidates=match["candidates"],
            )
        now = self.clock.now()
        bucket = {
            "bucket_id": allocate_bucket_id(self.store.list_buckets()),
            "schema_version": BUCKET_SCHEMA_VERSION,
            "task_intent": episode["task_intent"],
            "representative_actions": list(episode["actions"]),
            "environment_signature": environment_signature(episode),
            "episode_refs": [episode_ref(episode)],
            "distinct_trace_count": 1,
            "threshold": self.trace_threshold,
            "status": "ready_for_generation" if self.trace_threshold <= 1 else "collecting",
            "skill_id": None,
            "generation_error": None,
            "created_at": now,
            "updated_at": now,
        }
        problems = bucket_problems(bucket)
        if problems:
            return _fail("invalid_bucket", "Bucket failed validation.", details=problems)
        try:
            self.store.insert_bucket(bucket)
            self.store.assign_episode_bucket(episode["episode_id"], bucket["bucket_id"])
        except StoreError as exc:
            return _fail(exc.code, exc.message)
        return {"ok": True, "created": True, "bucket": self.store.get_bucket(bucket["bucket_id"])}

    def add_episode_to_bucket(self, bucket_id: str, episode_id: str) -> dict[str, Any]:
        if not isinstance(bucket_id, str) or not bucket_id:
            return _fail("invalid_bucket_id", "bucket_id must be a non-empty string.")
        if not isinstance(episode_id, str) or not episode_id:
            return _fail("invalid_episode_id", "episode_id must be a non-empty string.")
        bucket = self.store.get_bucket(bucket_id)
        if bucket is None:
            return _fail("unknown_bucket", f"Unknown bucket {bucket_id}.")
        episode = self.store.get_episode(episode_id)
        if episode is None:
            return _fail("unknown_episode", f"Unknown episode {episode_id}.")
        if any(ref["episode_id"] == episode_id for ref in bucket["episode_refs"]):
            return {"ok": True, "already_present": True, "bucket": bucket}
        evaluation = evaluate_bucket(
            episode, bucket, self.task_threshold, self.action_threshold
        )
        if not evaluation["accepted"]:
            return _fail(
                "not_compatible",
                "The episode does not match this bucket.",
                reasons=evaluation["reasons"],
            )
        current = episode.get("bucket_id")
        if current and current != bucket_id:
            return _fail("episode_already_bucketed", f"{episode_id} is already in {current}.")
        bucket["episode_refs"].append(episode_ref(episode))
        _apply_threshold(bucket)
        bucket["updated_at"] = self.clock.now()
        problems = bucket_problems(bucket)
        if problems:
            return _fail("invalid_bucket", "Bucket failed validation.", details=problems)
        try:
            self.store.replace_bucket(bucket)
            self.store.assign_episode_bucket(episode_id, bucket_id)
        except StoreError as exc:
            return _fail(exc.code, exc.message)
        return {"ok": True, "already_present": False, "bucket": self.store.get_bucket(bucket_id)}

    def get_bucket(self, bucket_id: str) -> dict[str, Any]:
        bucket = self.store.get_bucket(bucket_id)
        if bucket is None:
            return _fail("unknown_bucket", f"Unknown bucket {bucket_id}.")
        return {"ok": True, "bucket": bucket}

    def list_bucket_evidence(self, bucket_id: str) -> dict[str, Any]:
        bucket = self.store.get_bucket(bucket_id)
        if bucket is None:
            return _fail("unknown_bucket", f"Unknown bucket {bucket_id}.")
        episodes = []
        missing = []
        for ref in bucket["episode_refs"]:
            episode = self.store.get_episode(ref["episode_id"])
            if episode is None:
                missing.append(ref["episode_id"])
            else:
                episodes.append(episode)
        if missing:
            return _fail(
                "missing_evidence",
                "A referenced episode is not in the store.",
                missing_episode_ids=missing,
            )
        return {
            "ok": True,
            "bucket_id": bucket_id,
            "episode_refs": copy.deepcopy(bucket["episode_refs"]),
            "episodes": episodes,
        }

    def check_bucket_threshold(self, bucket_id: str) -> dict[str, Any]:
        bucket = self.store.get_bucket(bucket_id)
        if bucket is None:
            return _fail("unknown_bucket", f"Unknown bucket {bucket_id}.")
        before = copy.deepcopy(bucket)
        _apply_threshold(bucket)
        if bucket != before:
            bucket["updated_at"] = self.clock.now()
            problems = bucket_problems(bucket)
            if problems:
                return _fail("invalid_bucket", "Bucket failed validation.", details=problems)
            self.store.replace_bucket(bucket)
        reached = bucket["distinct_trace_count"] >= bucket["threshold"]
        return {
            "ok": True,
            "distinct_trace_count": bucket["distinct_trace_count"],
            "threshold": bucket["threshold"],
            "reached": reached,
            "status": bucket["status"],
            "bucket": bucket,
        }

    def review_proposal(self, episode: dict[str, Any], proposal: Any) -> dict[str, Any]:
        schema_errors = validate_instance(proposal, DECISION_SCHEMA)
        if schema_errors:
            return _fail("invalid_decision", "Assignment decision failed validation.", details=schema_errors)
        errors = validate_episode(episode)
        if errors:
            return _fail("invalid_episode", "Episode v2 validation failed.", details=errors)
        match = match_episode(
            episode,
            self.store.list_buckets(),
            task_threshold=self.task_threshold,
            action_threshold=self.action_threshold,
        )
        decision = proposal["decision"]
        candidate = proposal["candidate_bucket_id"]
        agrees = False
        if decision == "assign_existing":
            agrees = match["decision"] == "assign_existing" and candidate == match["selected_bucket_id"]
        elif decision == "create_new":
            agrees = match["decision"] == "create_new" and candidate is None
        elif decision == "ambiguous":
            agrees = match["decision"] == "ambiguous" and candidate is None
        if not agrees:
            return _fail(
                "proposal_rejected",
                "The proposal does not match the deterministic matcher. Confidence was not applied.",
                matcher_decision=match["decision"],
                matcher_bucket_id=match["selected_bucket_id"],
            )
        return {"ok": True, "accepted": True, "decision": decision, "match": match}


def bucket_problems(bucket: dict[str, Any]) -> list[str]:
    errors = validate_instance(bucket, BUCKET_SCHEMA)
    if errors:
        return errors
    unique = []
    seen = set()
    for ref in bucket["episode_refs"]:
        if ref["episode_id"] in seen:
            continue
        seen.add(ref["episode_id"])
        unique.append(ref)
    if len(unique) != len(bucket["episode_refs"]):
        errors.append("episode_refs contains a duplicate episode_id")
    if bucket["distinct_trace_count"] != len(unique):
        errors.append("distinct_trace_count must equal the unique episode references")
    signature = bucket["environment_signature"]
    if signature["permissions_known"] != (signature["permissions"] is not None):
        errors.append("permissions_known does not match permissions")
    if signature["constraints_known"] != (signature["constraints"] is not None):
        errors.append("constraints_known does not match constraints")
    if bucket["status"] == "skill_created":
        if not bucket["skill_id"] or bucket["generation_error"] is not None:
            errors.append("skill_created requires skill_id and no generation_error")
    elif bucket["status"] == "generation_failed":
        if bucket["skill_id"] is not None or not bucket["generation_error"]:
            errors.append("generation_failed requires generation_error and no skill_id")
    elif bucket["skill_id"] is not None or bucket["generation_error"] is not None:
        errors.append("collecting and ready buckets have no skill_id and no generation_error")
    return errors


def _apply_threshold(bucket: dict[str, Any]) -> dict[str, Any]:
    unique = []
    seen = set()
    for ref in bucket["episode_refs"]:
        if ref["episode_id"] in seen:
            continue
        seen.add(ref["episode_id"])
        unique.append(ref)
    bucket["episode_refs"] = unique
    bucket["distinct_trace_count"] = len(unique)
    count = bucket["distinct_trace_count"]
    if bucket["status"] == "collecting" and count >= bucket["threshold"]:
        bucket["status"] = "ready_for_generation"
    elif bucket["status"] == "ready_for_generation" and count < bucket["threshold"]:
        bucket["status"] = "collecting"
    return bucket


def _fail(code: str, message: str, **extra: Any) -> dict[str, Any]:
    body = {"ok": False, "error": code, "message": message}
    body.update(extra)
    return body
