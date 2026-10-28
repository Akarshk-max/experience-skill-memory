"""Assemble and check a candidate skill. Trusted fields are not taken from the draft."""

from __future__ import annotations

from typing import Any

from models import BANNED_REWARD_FIELDS, SKILL_SCHEMA_VERSION, build_reward_summary, skill_id_for
from schema_validate import load_schema, validate_instance

SKILL_SCHEMA = load_schema("skill.schema.json")


def assemble_skill(
    draft: Any,
    bucket: dict[str, Any],
    episodes: list[dict[str, Any]],
    now: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(draft, dict):
        return None, ["draft must be an object"]
    errors = _draft_errors(draft, episodes)
    if errors:
        return None, errors
    skill = {
        "skill_id": skill_id_for(bucket["bucket_id"]),
        "schema_version": SKILL_SCHEMA_VERSION,
        "bucket_id": bucket["bucket_id"],
        "name": draft.get("name"),
        "description": draft.get("description"),
        "status": "candidate",
        "version": 1,
        "trigger_conditions": draft.get("trigger_conditions"),
        "environment_conditions": draft.get("environment_conditions"),
        "procedure": draft.get("procedure"),
        "action_triggers": draft.get("action_triggers"),
        "success_criteria": draft.get("success_criteria"),
        "failure_handling": draft.get("failure_handling"),
        "constraints": draft.get("constraints"),
        "evidence_refs": list(bucket["episode_refs"]),
        "reward_summary": build_reward_summary(episodes),
        "created_at": now,
        "updated_at": now,
    }
    errors.extend(validate_instance(skill, SKILL_SCHEMA))
    if errors:
        return None, errors
    errors.extend(semantic_skill_errors(skill, bucket, episodes))
    if errors:
        return None, errors
    return skill, []


def semantic_skill_errors(
    skill: dict[str, Any],
    bucket: dict[str, Any],
    episodes: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    if skill["skill_id"] != skill_id_for(bucket["bucket_id"]):
        errors.append("skill_id is not derived from the bucket")
    if skill["bucket_id"] != bucket["bucket_id"]:
        errors.append("bucket_id does not match the evidence bucket")
    if skill["evidence_refs"] != bucket["episode_refs"]:
        errors.append("evidence_refs must be the bucket's episode references")
    episode_ids = [ref["episode_id"] for ref in bucket["episode_refs"]]
    if len(episode_ids) != len(set(episode_ids)):
        errors.append("bucket evidence is not distinct")
    step_ids = [step["step_id"] for step in skill["procedure"]]
    if step_ids != list(range(1, len(step_ids) + 1)):
        errors.append("procedure step_id values must be 1..n in order")
    allowed = set(episode_ids)
    for step in skill["procedure"]:
        if not set(step["evidence_refs"]) <= allowed:
            errors.append("a procedure step cites an episode outside the bucket")
    signature = bucket["environment_signature"]
    conditions = skill["environment_conditions"]
    if not set(conditions["required_tools"]) <= set(signature["available_tools"]):
        errors.append("required_tools include a tool that is not in the evidence")
    errors.extend(_permission_errors(conditions, signature))
    known_constraints = set(signature["constraints"] or []) if signature["constraints_known"] else set()
    if not set(conditions["prerequisites"]) <= known_constraints:
        errors.append("prerequisites include a value that is not in the evidence")
    if not set(skill["constraints"]) <= known_constraints:
        errors.append("constraints include a value that is not in the evidence")
    if skill["reward_summary"] != build_reward_summary(episodes):
        errors.append("reward_summary does not match computed step evidence")
    return errors


def _draft_errors(draft: dict[str, Any], episodes: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for field in BANNED_REWARD_FIELDS:
        if field in draft:
            errors.append(f"draft contains unsupported field {field}")
    if draft.get("status") not in (None, "candidate"):
        errors.append("status must be candidate")
    if "version" in draft and draft["version"] != 1:
        errors.append("version must be 1")
    if "schema_version" in draft and draft["schema_version"] != SKILL_SCHEMA_VERSION:
        errors.append("schema_version must be 1")
    summary = draft.get("reward_summary")
    if isinstance(summary, dict):
        for field in BANNED_REWARD_FIELDS:
            if field in summary:
                errors.append(f"reward_summary contains unsupported field {field}")
        if summary != build_reward_summary(episodes):
            errors.append("reward_summary does not match the evidence")
    elif "reward_summary" in draft:
        errors.append("reward_summary must be an object when it is supplied")
    return errors


def _permission_errors(conditions: dict[str, Any], signature: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if signature["permissions_known"]:
        if conditions["permissions"] != signature["permissions"]:
            errors.append("permissions do not match the evidence")
    elif conditions["permissions"] is not None:
        errors.append("permissions were not stated on the evidence")
    if signature["constraints_known"]:
        if conditions["constraints"] != signature["constraints"]:
            errors.append("environment constraints do not match the evidence")
    elif conditions["constraints"] is not None:
        errors.append("environment constraints were not stated on the evidence")
    return errors
