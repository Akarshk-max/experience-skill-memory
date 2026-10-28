"""Skill draft assembly is validated here. This module does not call a model provider."""

from __future__ import annotations

import re
from typing import Any

from models import build_reward_summary


def draft_from_evidence(bucket: dict[str, Any], episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic test draft grounded in the supplied episodes. Not an LLM completion."""
    by_id = {episode["episode_id"]: episode for episode in episodes}
    ordered = [
        by_id[ref["episode_id"]]
        for ref in bucket["episode_refs"]
        if ref["episode_id"] in by_id
    ]
    signature = bucket["environment_signature"]
    procedure = []
    triggers = []
    for number, action in enumerate(bucket["representative_actions"], start=1):
        cited = [episode["episode_id"] for episode in ordered if action in episode.get("actions", [])]
        if not cited and ordered:
            cited = [ordered[0]["episode_id"]]
        procedure.append(
            {
                "step_id": number,
                "instruction": f"Perform the evidenced action: {action}",
                "expected_observation": _shared_observation(ordered, action),
                "evidence_refs": cited,
            }
        )
        triggers.append(
            {
                "condition": f"The current step calls for the evidenced action {action}",
                "action": action,
            }
        )
    outcomes = sorted({episode["outcome"] for episode in ordered})
    failure = [f"Evidence includes stored outcomes: {', '.join(outcomes)}."]
    if any(_has_negative_reward(episode) for episode in ordered):
        failure.append(
            "At least one progress-delta step reward in the evidence is negative. "
            "Use it as a caution, not as proof of the stored outcome."
        )
    if any(episode["outcome"] == "success" for episode in ordered):
        success = ["A stored outcome of success appears in the evidence."]
    else:
        success = ["No stored success outcome is in the evidence."]
    intent = bucket.get("task_intent")
    if isinstance(intent, str) and intent:
        trigger = f"The task intent matches the evidence: {intent}"
        name_source = intent
    else:
        trigger = "The source episodes did not state a task_intent."
        name_source = "unspecified_task"
    known_constraints = list(signature["constraints"]) if signature["constraints_known"] else []
    return {
        "name": _name(name_source),
        "description": (
            f"Candidate skill from {len(ordered)} distinct episodes. "
            f"Task intent: {intent if intent else 'not stated'}."
        ),
        "status": "candidate",
        "version": 1,
        "schema_version": 1,
        "trigger_conditions": [trigger],
        "environment_conditions": {
            "required_tools": list(signature["available_tools"]),
            "permissions": None if not signature["permissions_known"] else list(signature["permissions"]),
            "prerequisites": [],
            "constraints": None if not signature["constraints_known"] else list(signature["constraints"]),
        },
        "procedure": procedure,
        "action_triggers": triggers,
        "success_criteria": success,
        "failure_handling": failure,
        "constraints": known_constraints,
        "reward_summary": build_reward_summary(ordered),
    }


class FakeSkillGenerator:
    """Test double. `generate` does not contact a model provider."""

    def __init__(self, mode: str = "valid") -> None:
        self.mode = mode
        self.calls = 0

    def generate(self, bucket: dict[str, Any], episodes: list[dict[str, Any]]) -> Any:
        self.calls += 1
        if self.mode == "raise":
            raise RuntimeError("generator unavailable")
        if self.mode == "not_a_dict":
            return ["not", "a", "skill"]
        draft = draft_from_evidence(bucket, episodes)
        if self.mode == "published":
            draft["status"] = "published"
        elif self.mode == "unknown_tool":
            draft["environment_conditions"]["required_tools"] = ["not_in_evidence"]
        elif self.mode == "bad_reward":
            draft["reward_summary"] = {
                "method": "progress_delta",
                "aggregation": "sum",
                "computed_steps": [],
                "episodes_without_computed_reward": 0,
                "note": "summed",
            }
        elif self.mode == "invented_permission":
            draft["environment_conditions"]["permissions"] = ["admin"]
        elif self.mode == "unknown_evidence":
            if draft["procedure"]:
                draft["procedure"][0]["evidence_refs"] = ["ep_missing"]
        elif self.mode == "omit_reward":
            draft.pop("reward_summary", None)
        elif self.mode == "trajectory":
            draft["trajectory_reward"] = 1
        return draft


def _shared_observation(episodes: list[dict[str, Any]], action: str) -> str | None:
    found = []
    for episode in episodes:
        for step in episode.get("steps") or []:
            if step.get("action") == action and isinstance(step.get("observation"), str):
                found.append(step["observation"])
    if found and all(item == found[0] for item in found):
        return found[0]
    return None


def _has_negative_reward(episode: dict[str, Any]) -> bool:
    for step in episode.get("steps") or []:
        reward = step.get("step_reward")
        status = (step.get("reward_metadata") or {}).get("status")
        if status == "computed" and isinstance(reward, (int, float)) and not isinstance(reward, bool):
            if reward < 0:
                return True
    return False


def _name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return (cleaned or "unspecified_task")[:80]
