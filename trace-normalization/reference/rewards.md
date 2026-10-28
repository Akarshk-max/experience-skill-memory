# Step rewards

`normalize_trace` reserves a progress-delta reward on every step and does not fill it. No grading model is connected. The formula is a research-inspired proposal, not a verified reproduction of a paper.

```text
step_reward = p_after - p_before
```

`p_before` and `p_after` are estimates of the probability that the task succeeds, before and after the step. They are not read from the trace.

## What normalization writes

Each step:

- `step_reward`: `null`
- `reward_metadata.method`: `progress_delta`
- `reward_metadata.status`: `pending`
- `reward_metadata.p_before`, `p_after`, and `rationale`: `null`

The episode:

- `reward_metadata.method`: `progress_delta`
- `reward_metadata.status`: `pending`
- `reward_metadata.aggregation`: `not_defined`

`aggregation: not_defined` means no trajectory sum, average, or discount is part of this contract. A step reward is not the episode outcome. `outcome` remains the stored status.

## What `apply_progress_grades` writes

The caller passes `{index, p_before, p_after, rationale?}`. The function returns a copy of the episode.

| Input | Step status | Stored values |
| --- | --- | --- |
| Both probabilities are numbers in [0, 1] | `computed` | The probabilities and `p_after - p_before`. Rationale only if the caller passed a string. |
| One probability is missing or null | `pending` | Reward, probabilities, and rationale stay null. |
| A probability is a bool, a non-number, NaN, infinite, or outside [0, 1] | `rejected` | Reward, probabilities, and rationale stay null. The rejected numbers are not kept. |
| Grades is not a list, or the index is not a step | unchanged | That step stays as normalization left it. |

A stored rationale is redacted with the same text rules as step text. The function does not write a rationale the caller did not supply, and it does not change `outcome`, `actions`, or `bucket_id`. Episode aggregation stays `not_defined`.
