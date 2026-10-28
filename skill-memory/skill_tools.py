"""Read and assemble skills. Storage of a passing skill is done by the creation service."""

from __future__ import annotations

from typing import Any

from skill_validation import assemble_skill


class SkillTools:
    def __init__(self, store: Any, clock: Any) -> None:
        self.store = store
        self.clock = clock

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        if not isinstance(skill_id, str) or not skill_id:
            return {"ok": False, "error": "invalid_skill_id", "message": "skill_id must be a non-empty string."}
        skill = self.store.get_skill(skill_id)
        if skill is None:
            return {"ok": False, "error": "unknown_skill", "message": f"Unknown skill {skill_id}."}
        return {"ok": True, "skill": skill}

    def assemble(self, draft: Any, bucket: dict[str, Any], episodes: list[dict[str, Any]]) -> dict[str, Any]:
        skill, errors = assemble_skill(draft, bucket, episodes, self.clock.now())
        if errors:
            return {
                "ok": False,
                "error": "invalid_skill",
                "message": "Skill draft failed validation.",
                "details": errors,
            }
        return {"ok": True, "skill": skill}
