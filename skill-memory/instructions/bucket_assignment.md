# Bucket assignment

You assign one normalized Episode v2 to an evidence bucket. You do not generate a skill in this step. You do not invent episode fields, rewards, tools, permissions, or outcomes.

The executable rules are in `reference/bucket-matching.md`. Trusted code in `bucket_assignment.py` and `bucket_tools.py` is the authority. If your judgment and that code disagree, the code wins and the write is refused.

## Read the episode

Use only:

- `task_intent`
- ordered `actions`
- `environment.available_tools`, `environment.permissions`, and `environment.constraints`
- `episode_id` as the identity

Ignore `step_reward`, `reward_metadata`, and `outcome` for matching. A missing `task_intent` is unknown. Unknown does not match another unknown. Null permissions are unknown. Unknown does not match a known permission list. An empty `available_tools` list means no tools were observed, and it matches only that same set.

## Search before you decide

Call `search_buckets` with the episode. Read the returned `decision`, `selected_bucket_id`, scores, and reasons. Consider task intent first, then action order, then environment compatibility.

Default acceptance is task score at least 0.6 and action score at least 0.6, plus an environment that is not incompatible, on a bucket that is not `skill_created`. Those cutoffs are prototype settings. Do not lower them in the decision.

## Decision

Return one object and nothing else:

```json
{
  "decision": "assign_existing",
  "candidate_bucket_id": "bkt_0001",
  "reason": "Task, action order, and environment agree with the matcher.",
  "confidence": 0.8
}
```

`decision` is `assign_existing`, `create_new`, or `ambiguous`.

- `assign_existing`: set `candidate_bucket_id` to the one selected bucket.
- `create_new`: set `candidate_bucket_id` to null. Use this when the matcher found no suitable open bucket.
- `ambiguous`: set `candidate_bucket_id` to null. Use this when two open buckets tie on task score and action score. Do not pick one.

`confidence` is a number from 0 to 1, or null. It does not override a tool rejection, an environment mismatch, or a tie.

## Tools

Use only these tools:

- `search_buckets(episode)`
- `create_bucket(episode)` when the decision is `create_new` and trusted code agrees
- `add_episode_to_bucket(bucket_id, episode_id)` when the decision is `assign_existing` and trusted code agrees
- `get_bucket(bucket_id)`
- `list_bucket_evidence(bucket_id)`
- `check_bucket_threshold(bucket_id)`

Do not pass a count, a status, or a threshold. Trusted code recomputes `distinct_trace_count`, drops duplicate episode ids, and sets `collecting` or `ready_for_generation`. A repeated add of the same episode id is an idempotent no-op.

Do not call skill generation tools. Do not write a skill, a reward, or a bucket id onto the episode yourself.
