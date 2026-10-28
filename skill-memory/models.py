"""Shared constants and Episode v2 checks for the skill-memory prototype."""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Any

BUCKET_SCHEMA_VERSION = 1
SKILL_SCHEMA_VERSION = 1
EPISODE_SCHEMA_VERSION = 2

BUCKET_STATUSES = (
    "collecting",
    "ready_for_generation",
    "generation_failed",
    "skill_created",
)
EVENT_TYPES = ("action_run", "action_graph_run", "action_team_run", "tool_run")
RUN_OUTCOMES = ("success", "error", "cancelled")
TOOL_OUTCOMES = ("success", "error", "cancelled", "stuck")

# Engineering defaults for this prototype. They are not a universal similarity law.
DEFAULT_TASK_THRESHOLD = 0.6
DEFAULT_ACTION_THRESHOLD = 0.6
DEFAULT_TRACE_THRESHOLD = 3

REWARD_NOTE = (
    "Computed values are progress-delta step estimates. "
    "They are not a trajectory reward and they are not the stored outcome."
)
BANNED_REWARD_FIELDS = ("total_reward", "trajectory_reward", "return", "advantage", "score")


class FixedClock:
    def __init__(self, instant: str = "2026-10-29T00:00:00+00:00") -> None:
        self.instant = instant

    def now(self) -> str:
        return self.instant


class SystemClock:
    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


def episode_body(episode: dict[str, Any]) -> dict[str, Any]:
    body = copy.deepcopy(episode)
    body.pop("bucket_id", None)
    return body


def episode_ref(episode: dict[str, Any]) -> dict[str, str]:
    return {
        "episode_id": episode["episode_id"],
        "source_run_id": episode["source_run_id"],
        "event_type": episode["event_type"],
        "outcome": episode["outcome"],
    }


def environment_signature(episode: dict[str, Any]) -> dict[str, Any]:
    env = episode["environment"]
    permissions = env["permissions"]
    constraints = env["constraints"]
    return {
        "available_tools": _unique_strings(env["available_tools"]),
        "permissions": None if permissions is None else _unique_strings(permissions),
        "constraints": None if constraints is None else _unique_strings(constraints),
        "permissions_known": permissions is not None,
        "constraints_known": constraints is not None,
    }


def allocate_bucket_id(buckets: list[dict[str, Any]]) -> str:
    highest = 0
    for bucket in buckets:
        match = re.fullmatch(r"bkt_(\d+)", bucket.get("bucket_id", ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"bkt_{highest + 1:04d}"


def skill_id_for(bucket_id: str) -> str:
    return f"skl_{bucket_id}"


def pending_step_reward() -> dict[str, Any]:
    return {
        "method": "progress_delta",
        "p_before": None,
        "p_after": None,
        "status": "pending",
        "rationale": None,
    }


def validate_episode(episode: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(episode, dict):
        return ["episode must be an object"]
    required = (
        "episode_id",
        "schema_version",
        "source_run_id",
        "event_type",
        "source",
        "task_intent",
        "actions",
        "environment",
        "outcome",
        "steps",
        "reward_metadata",
        "bucket_id",
        "warnings",
    )
    for key in required:
        if key not in episode:
            errors.append(f"missing {key}")
    if errors:
        return errors
    if episode["schema_version"] != EPISODE_SCHEMA_VERSION:
        errors.append("schema_version must be 2")
    if not isinstance(episode["episode_id"], str) or not episode["episode_id"]:
        errors.append("episode_id must be a non-empty string")
    if episode["source_run_id"] != episode["episode_id"]:
        errors.append("source_run_id must equal episode_id")
    if episode["event_type"] not in EVENT_TYPES:
        errors.append("event_type is not an execution type")
    source = episode["source"]
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        if source.get("collection") != "EventResults":
            errors.append("source.collection must be EventResults")
        if source.get("source_run_id") != episode["episode_id"]:
            errors.append("source.source_run_id must equal episode_id")
        if source.get("event_type") != episode["event_type"]:
            errors.append("source.event_type must equal event_type")
    intent = episode["task_intent"]
    if intent is not None and not isinstance(intent, str):
        errors.append("task_intent must be a string or null")
    if not isinstance(episode["actions"], list) or not all(isinstance(item, str) for item in episode["actions"]):
        errors.append("actions must be a list of strings")
    errors.extend(_validate_environment(episode.get("environment")))
    allowed = TOOL_OUTCOMES if episode["event_type"] == "tool_run" else RUN_OUTCOMES
    if episode["outcome"] not in allowed:
        errors.append("outcome is not a stored terminal status for this event type")
    if episode["bucket_id"] is not None and not isinstance(episode["bucket_id"], str):
        errors.append("bucket_id must be a string or null")
    if not isinstance(episode["warnings"], list):
        errors.append("warnings must be a list")
    reward = episode["reward_metadata"]
    if not isinstance(reward, dict):
        errors.append("reward_metadata must be an object")
    elif (
        reward.get("method") != "progress_delta"
        or reward.get("status") != "pending"
        or reward.get("aggregation") != "not_defined"
    ):
        errors.append("episode reward aggregation must stay pending and not_defined")
    if not isinstance(episode["steps"], list):
        errors.append("steps must be a list")
    else:
        for index, step in enumerate(episode["steps"]):
            errors.extend(_validate_step(step, index))
    return errors


def build_reward_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """List computed progress-delta steps. Do not sum them."""
    computed: list[dict[str, Any]] = []
    without = 0
    for episode in episodes:
        found = False
        for step in episode.get("steps") or []:
            meta = step.get("reward_metadata") or {}
            reward = step.get("step_reward")
            if meta.get("status") != "computed":
                continue
            if isinstance(reward, bool) or not isinstance(reward, (int, float)):
                continue
            computed.append(
                {
                    "episode_id": episode["episode_id"],
                    "step_index": step["index"],
                    "step_reward": reward,
                    "method": "progress_delta",
                }
            )
            found = True
        if not found:
            without += 1
    return {
        "method": "progress_delta",
        "aggregation": "not_defined",
        "computed_steps": computed,
        "episodes_without_computed_reward": without,
        "note": REWARD_NOTE,
    }


def _validate_environment(environment: Any) -> list[str]:
    if not isinstance(environment, dict):
        return ["environment must be an object"]
    errors: list[str] = []
    tools = environment.get("available_tools")
    if not isinstance(tools, list) or not all(isinstance(item, str) and item for item in tools):
        errors.append("available_tools must be a list of non-empty strings")
    for key in ("permissions", "constraints"):
        value = environment.get(key, "missing")
        if value is None:
            continue
        if value == "missing":
            errors.append(f"{key} is required")
            continue
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            errors.append(f"{key} must be null or a non-empty list of strings")
    return errors


def _validate_step(step: Any, index: int) -> list[str]:
    prefix = f"steps[{index}]"
    if not isinstance(step, dict):
        return [f"{prefix} must be an object"]
    errors: list[str] = []
    if step.get("index") != index:
        errors.append(f"{prefix}.index must equal its position")
    meta = step.get("reward_metadata")
    if not isinstance(meta, dict):
        return errors + [f"{prefix}.reward_metadata must be an object"]
    if meta.get("method") != "progress_delta":
        errors.append(f"{prefix} reward method must be progress_delta")
    status = meta.get("status")
    reward = step.get("step_reward", "missing")
    if status in ("pending", "rejected"):
        if reward is not None or meta.get("p_before") is not None or meta.get("p_after") is not None:
            errors.append(f"{prefix} pending or rejected reward must stay null")
    elif status == "computed":
        before = meta.get("p_before")
        after = meta.get("p_after")
        if not _probability(before) or not _probability(after):
            errors.append(f"{prefix} computed reward needs probabilities in [0, 1]")
        elif reward != after - before:
            errors.append(f"{prefix}.step_reward must equal p_after - p_before")
    else:
        errors.append(f"{prefix} reward status is not pending, computed, or rejected")
    rationale = meta.get("rationale", None)
    if rationale is not None and not isinstance(rationale, str):
        errors.append(f"{prefix} rationale must be a string or null")
    if "step_reward" not in step:
        errors.append(f"{prefix} is missing step_reward")
    return errors


def _probability(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and 0 <= value <= 1
    )


def _unique_strings(values: list[Any]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.append(value)
    return seen
