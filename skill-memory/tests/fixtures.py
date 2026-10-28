"""Shared episode builders for skill-memory tests."""

from __future__ import annotations

import copy
from typing import Any

from models import FixedClock, environment_signature, episode_ref
from skill_draft import FakeSkillGenerator
from skill_generation import SkillCreationService
from storage.memory_store import MemoryStore


def make_episode(
    episode_id: str,
    *,
    task: str | None = "debug api timeout",
    actions: list[str] | None = None,
    tools: list[str] | None = None,
    permissions: list[str] | None = None,
    constraints: list[str] | None = None,
    outcome: str = "success",
    event_type: str = "action_run",
    steps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    actions = ["inspect_logs"] if actions is None else list(actions)
    tools = [] if tools is None else list(tools)
    if steps is None:
        steps = [_pending_step(index, action) for index, action in enumerate(actions)]
    return {
        "episode_id": episode_id,
        "schema_version": 2,
        "source_run_id": episode_id,
        "event_type": event_type,
        "source": {
            "collection": "EventResults",
            "source_run_id": episode_id,
            "event_type": event_type,
        },
        "task_intent": task,
        "actions": actions,
        "environment": {
            "available_tools": tools,
            "permissions": permissions,
            "constraints": constraints,
        },
        "outcome": outcome,
        "steps": steps,
        "reward_metadata": {
            "method": "progress_delta",
            "status": "pending",
            "aggregation": "not_defined",
        },
        "bucket_id": None,
        "warnings": [],
    }


def computed_step(
    index: int,
    action: str,
    p_before: float,
    p_after: float,
    *,
    observation: str | None = None,
    rationale: str | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "index": index,
        "action": action,
        "step_reward": p_after - p_before,
        "reward_metadata": {
            "method": "progress_delta",
            "p_before": p_before,
            "p_after": p_after,
            "status": "computed",
            "rationale": rationale,
        },
    }
    if observation is not None:
        step["observation"] = observation
    return step


def service(
    *,
    threshold: int = 3,
    task_threshold: float = 0.6,
    action_threshold: float = 0.6,
    generator: Any = None,
    store: Any = None,
    vector_index: Any = None,
) -> SkillCreationService:
    return SkillCreationService(
        store or MemoryStore(),
        threshold=threshold,
        task_threshold=task_threshold,
        action_threshold=action_threshold,
        generator=generator,
        clock=FixedClock(),
        vector_index=vector_index,
    )


def seed_bucket(store: MemoryStore, bucket_id: str, episode: dict[str, Any], threshold: int = 3) -> None:
    episode = copy.deepcopy(episode)
    episode["bucket_id"] = None
    store.put_episode(episode)
    store.assign_episode_bucket(episode["episode_id"], bucket_id)
    now = "2026-10-29T00:00:00+00:00"
    store.insert_bucket(
        {
            "bucket_id": bucket_id,
            "schema_version": 1,
            "task_intent": episode["task_intent"],
            "representative_actions": list(episode["actions"]),
            "environment_signature": environment_signature(episode),
            "episode_refs": [episode_ref(episode)],
            "distinct_trace_count": 1,
            "threshold": threshold,
            "status": "collecting",
            "skill_id": None,
            "generation_error": None,
            "created_at": now,
            "updated_at": now,
        }
    )


def generator(mode: str = "valid") -> FakeSkillGenerator:
    return FakeSkillGenerator(mode)


def _pending_step(index: int, action: str) -> dict[str, Any]:
    return {
        "index": index,
        "action": action,
        "step_reward": None,
        "reward_metadata": {
            "method": "progress_delta",
            "p_before": None,
            "p_after": None,
            "status": "pending",
            "rationale": None,
        },
    }
