# Bucket matching

This is the deterministic matcher used by `bucket_assignment.py`. It is an engineering choice for the prototype, not a universal similarity threshold and not an embedding score.

Rewards are ignored. `step_reward` does not affect membership or the distinct-trace threshold.

## Normalization

A label is lowercased. Every character that is not a letter or digit becomes a space. The result is stripped. Task tokens are the space-separated words. Each action stays one item: the whole action string is normalized, then the items stay in order.

`debug_api_timeout` and `Debug API Timeout` both become the tokens `debug`, `api`, `timeout`. The bucket keeps the seed episode's original `task_intent` and action strings.

An empty result is missing. Missing is not equal to another missing value.

## Scores

Task score is the Jaccard overlap of the two token sets: `|intersection| / |union|`. If either set is empty the score is 0.

Action score is the length of the longest common subsequence of the normalized action lists, divided by the longer list. Subsequence matching keeps relative order and allows gaps. If either list is empty the score is 0.

Two reversed distinct actions of length 2 score `1 / 2 = 0.5`.

## Environment

`available_tools` is an observed fact, including an empty list. The sets must be equal. Order does not matter. Different sets are incompatible.

`permissions` and `constraints` use a different rule because null means unknown:

| Episode | Bucket signature | Result |
| --- | --- | --- |
| null | null | No contradiction. Certainty stays `partial`. This is not proof that the permissions are the same. |
| null | a list, or the reverse | Incompatible. Unknown is not a match for a known list. |
| list | list | Compatible only when the sets are equal. Certainty is `full` only when tools, permissions, and constraints are all known and equal. |

## Acceptance

Default cutoffs, both configurable on `SkillCreationService`:

- task score `>= 0.6`
- action score `>= 0.6`
- environment is not incompatible
- the bucket status is not `skill_created`

`0.6` is the prototype default. A borderline case at exactly 0.6 is accepted. A lower score is not. Callers can pass a different cutoff. The tests cover `0.5` and `0.6`.

A closed `skill_created` bucket is not a candidate. A later similar episode opens a new bucket.

## Decision and ties

Among accepted open buckets:

- one candidate: `assign_existing`
- two or more with the same task score and the same action score: `ambiguous`, and nothing is written
- otherwise: `assign_existing` to the higher task score, then the higher action score

Equal scores do not fall through to `bucket_id`. An ambiguous result is not a silent assignment.

No accepted bucket: `create_new`. The new bucket copies the seed episode's task, ordered actions, and environment signature. Later episodes do not rewrite that signature.

## Threshold

`distinct_trace_count` is the number of unique `episode_id` values in `episode_refs`. The default count is 3 and is configurable per service. Reaching it sets `ready_for_generation` only from `collecting`. It does not sum rewards.

`check_bucket_threshold` recomputes the count from the references and persists that count.
