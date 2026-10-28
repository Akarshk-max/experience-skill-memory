"""Deterministic bucket matching.

Scores are an engineering choice for this prototype. See reference/bucket-matching.md.
"""

from __future__ import annotations

import re
from typing import Any

from models import DEFAULT_ACTION_THRESHOLD, DEFAULT_TASK_THRESHOLD

_TOKEN = re.compile(r"[^a-z0-9]+")


def normalize_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = _TOKEN.sub(" ", value.lower()).strip()
    return text or None


def tokenize(value: Any) -> list[str]:
    text = normalize_label(value)
    if text is None:
        return []
    return text.split(" ")


def jaccard(left: list[str], right: list[str]) -> float:
    first, second = set(left), set(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def action_score(left_actions: list[Any], right_actions: list[Any]) -> float:
    left = _action_sequence(left_actions)
    right = _action_sequence(right_actions)
    if not left or not right:
        return 0.0
    return _lcs_length(left, right) / max(len(left), len(right))


def match_episode(
    episode: dict[str, Any],
    buckets: list[dict[str, Any]],
    *,
    task_threshold: float = DEFAULT_TASK_THRESHOLD,
    action_threshold: float = DEFAULT_ACTION_THRESHOLD,
) -> dict[str, Any]:
    candidates = [
        evaluate_bucket(episode, bucket, task_threshold, action_threshold) for bucket in buckets
    ]
    candidates.sort(key=_candidate_sort)
    accepted = [item for item in candidates if item["accepted"]]
    if not accepted:
        decision = "create_new"
        selected = None
        reason = "No open bucket met the task, action, and environment rules."
    elif len(accepted) == 1:
        decision = "assign_existing"
        selected = accepted[0]["bucket_id"]
        reason = "One open bucket met the task, action, and environment rules."
    else:
        top, second = accepted[0], accepted[1]
        if top["task_score"] == second["task_score"] and top["action_score"] == second["action_score"]:
            decision = "ambiguous"
            selected = None
            reason = "More than one open bucket met the rules with equal task and action scores."
        else:
            decision = "assign_existing"
            selected = top["bucket_id"]
            reason = "Selected the open bucket with the higher task score, then the higher action score."
    return {
        "decision": decision,
        "selected_bucket_id": selected,
        "reason": reason,
        "candidates": candidates,
        "task_threshold": task_threshold,
        "action_threshold": action_threshold,
    }


def evaluate_bucket(
    episode: dict[str, Any],
    bucket: dict[str, Any],
    task_threshold: float,
    action_threshold: float,
) -> dict[str, Any]:
    task = jaccard(tokenize(episode.get("task_intent")), tokenize(bucket.get("task_intent")))
    left = _action_sequence(episode.get("actions") or [])
    right = _action_sequence(bucket.get("representative_actions") or [])
    score = 0.0 if not left or not right else _lcs_length(left, right) / max(len(left), len(right))
    compatible, certainty, environment_reason = environment_relation(
        episode["environment"], bucket["environment_signature"]
    )
    reasons: list[str] = []
    if bucket.get("status") == "skill_created":
        reasons.append("bucket_closed")
    if not tokenize(episode.get("task_intent")) or not tokenize(bucket.get("task_intent")):
        reasons.append("missing_task_intent")
    elif task < task_threshold:
        reasons.append("task_below_threshold")
    if not left or not right:
        reasons.append("missing_actions")
    elif score < action_threshold:
        reasons.append("action_below_threshold")
    if not compatible:
        reasons.append(environment_reason)
    return {
        "bucket_id": bucket["bucket_id"],
        "task_score": task,
        "action_score": score,
        "environment_certainty": certainty,
        "accepted": not reasons,
        "reasons": reasons,
    }


def environment_relation(environment: dict[str, Any], signature: dict[str, Any]) -> tuple[bool, str, str]:
    if _string_set(environment.get("available_tools")) != _string_set(signature.get("available_tools")):
        return False, "incompatible", "available_tools_differ"
    permissions_ok, permissions_unknown, permissions_reason = _known_field(
        environment.get("permissions"), signature.get("permissions"), "permissions"
    )
    constraints_ok, constraints_unknown, constraints_reason = _known_field(
        environment.get("constraints"), signature.get("constraints"), "constraints"
    )
    if not permissions_ok:
        return False, "incompatible", permissions_reason
    if not constraints_ok:
        return False, "incompatible", constraints_reason
    if permissions_unknown or constraints_unknown:
        return True, "partial", "unknown_permissions_or_constraints"
    return True, "full", "environment_compatible"


def _known_field(left: Any, right: Any, name: str) -> tuple[bool, bool, str]:
    if left is None and right is None:
        return True, True, f"{name}_unknown"
    if left is None or right is None:
        return False, True, f"{name}_unknown_mismatch"
    if _string_set(left) != _string_set(right):
        return False, False, f"{name}_differ"
    return True, False, f"{name}_match"


def _string_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {item.strip() for item in values if isinstance(item, str) and item.strip()}


def _action_sequence(actions: list[Any]) -> list[str]:
    sequence: list[str] = []
    for action in actions:
        label = normalize_label(action)
        if label:
            sequence.append(label)
    return sequence


def _lcs_length(left: list[str], right: list[str]) -> int:
    previous = [0] * (len(right) + 1)
    for item in left:
        current = [0]
        for index, other in enumerate(right, start=1):
            if item == other:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def _candidate_sort(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        not item["accepted"],
        -(item["task_score"] or 0.0),
        -(item["action_score"] or 0.0),
        item["bucket_id"],
    )
