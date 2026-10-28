# Skill generation

You write one candidate skill from one bucket that trusted code has marked ready. You do not search existing skills, revise a skill, or publish one.

No model provider is connected to this prototype. `FakeSkillGenerator` is a test double. A future model should follow this text and return a draft. `skill_validation.py` rejects drafts that break the schema or the evidence rules below.

## Read the evidence

You receive the bucket and the normalized episodes cited by `episode_refs`. Read:

- the bucket `task_intent`, `representative_actions`, and `environment_signature`
- each episode's ordered actions, observations, tool results, errors, stored `outcome`, and step reward metadata
- `source_run_id` and `event_type` on each reference

Use patterns that show up across the distinct episodes. Do not copy an account id, a one-off sentence, or an observation that the episodes do not share. If observations for the same action disagree, leave `expected_observation` null.

## Rewards

Progress delta is `step_reward = p_after - p_before` when `reward_metadata.status` is `computed`. Those numbers are estimates, not proof that the task succeeded.

- Prefer procedure steps whose computed rewards are consistently non-negative and whose stored outcomes are successful.
- A negative computed reward is a caution. Put that caution in `failure_handling`. Do not treat it as the stored outcome.
- `pending` and `rejected` rewards are missing. Leave them out. Do not invent probabilities, rationales, or a trajectory sum.
- Do not set `aggregation` to anything but `not_defined`. Omit `reward_summary` if you are unsure. Trusted code fills it from the episodes and rejects a summary that disagrees.

Stored `outcome` remains the verified terminal status. Do not replace it with a reward.

## What to produce

Return one JSON object that can become `schemas/skill.schema.json`. Include:

- `name` and `description` drawn from the shared task intent
- `status`: `candidate`
- `version`: 1
- `trigger_conditions`: when this skill should be considered
- `environment_conditions.required_tools`: only tools present on the bucket signature
- `environment_conditions.permissions` and `constraints`: the signature values, or null when `permissions_known` or `constraints_known` is false
- `environment_conditions.prerequisites`: only strings that already appear as known constraints; otherwise `[]`
- `procedure`: ordered steps with `step_id` starting at 1, an instruction, a shared expected observation or null, and episode ids from this bucket
- `action_triggers`: a condition and the action to take
- `success_criteria` and `failure_handling` grounded in stored outcomes and negative rewards
- `constraints`: known constraint strings only, otherwise `[]`

Do not invent tools, permissions, prerequisites, or a guaranteed outcome. Do not emit `skill_id`, timestamps, `total_reward`, `trajectory_reward`, or a published status. Trusted code sets the id, the evidence references, the timestamps, and the reward summary, then stores the skill only if validation passes.

If validation fails, the bucket becomes `generation_failed` and no skill is stored. A later retry can generate again from the same episode references.
