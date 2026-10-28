---
name: trace-normalization
description: Converts one completed Autobots execution trace into an ordered episode with source provenance, task and environment metadata, and the stored terminal status. Reserves per-step progress-delta rewards as pending until explicit probability estimates are supplied. Use when normalizing an action_run, action_graph_run, action_team_run, or tool_run before later bucket matching. Does not call a model, invent scores, assign buckets, or fetch storage.
disable-model-invocation: true
---

# Trace Normalization

Normalize one completed Autobots run into one episode. The episode preserves the observed steps and the status stored on the document, and it reserves fields that a later stage needs for bucket matching and step-reward grading.

Use `normalize_trace.py` as the executable contract. Do not import the Autobots application, `experience_memory`, or a model provider. No provider is connected.

Four kinds of work stay separate:

| Work | Who does it | What it may do |
| --- | --- | --- |
| Deterministic normalization | `normalize_trace` | Read the document, order steps, redact, and fill metadata that is copied or derived from those steps. |
| Semantic extraction and probability estimates | A future grading model, not this package | Read the episode and estimate `p_before` and `p_after`. This package does not call that model. |
| Reward arithmetic | `apply_progress_grades` | Compute `p_after - p_before` only from estimates the caller passed in. |
| Validation | `schema/episode.schema.json` and the tests | Check types, required fields, and the outcome enum. |

## 1. Identify a completed agent execution

A completed execution is one retrieved document whose `type` is `action_run`, `action_graph_run`, `action_team_run`, or `tool_run`, whose `status` is terminal for that type, and whose trace body is on the document.

Terminal statuses:

- action, graph, and team: `success`, `error`, `cancelled`
- tool: those three, plus `stuck`

`datastore_put` is a data event, not an agent trace. Reject it.

Pass the retrieved document only. This skill does not open MongoDB or object storage.

- An action run's Mongo document is authoritative for everything except `result`. When `file_url` is set, `result` must be the object from `action_runs/{user_id}/{run_id}.json`. The reader copies that object onto the Mongo document. If those bytes were missing, the reader raises "Action result payload missing in S3". Do not pass the lite document in that case.
- A graph or team run's full document is `{id}.json` under `runs/{user_id}/`. Empty bytes fall back to Mongo. Any exception from those readers returns `None`. `None` is a retrieval failure, not proof that the run is missing.
- A tool run is the Mongo document. There is no object-storage hydration.

If the caller has no document, stop. Do not invent a trace.

## 2. Decompose the run into ordered steps

Read `reference/trace-formats.md` and `reference/ordering-and-fallbacks.md`. Short form:

1. Action: use a non-empty `config.input_archive` when it yields steps. Otherwise use `results` in list order. Otherwise use the document `input` and `output`.
2. Graph with context entries: one step per context entry, nodes in stored key order, entries ordered by `sort_key`. Do not expand an output node's inner `results` or archive in this mode.
3. Graph with no context entries: walk `output` in stored key order and normalize each value as an action document.
4. Team: walk `thread` in list order. If it yields nothing, use `results`, then top-level `input` and `output`.
5. Tool: one step. `action` is `tool_name`. Arguments are `tool_args`. The result is `output`.

`input_archive` is the OpenAI Responses archive (`TurnArchiveEntry`). Traces that do not have it use `results` or `input`/`output`. Do not require an archive.

Skip message types `reasoning` and `compaction`. Pair a tool result to the earlier call with the same `call_id` or `tool_call_id`. Keep `human_questions` beside the steps, using `turn_index`. Do not insert them into the step list.

`steps[i].index` is the observed position, starting at 0. That index is the step id. Do not add a second id and do not renumber from 1.

## 3. Preserve actions, observations, tool results, errors, and provenance

Copy only fields that were on the source step. Omit a field that was missing. Do not replace a missing observation with the episode outcome, and do not copy the episode outcome onto every step as `result`. The row status, when present, is `step_status`.

Provenance lives on `source`: collection `EventResults`, the run id, event type, and `user_id`, canonical `file_url`, `parent_action_result_id`, and `run_kind` when those strings exist. `episode_id` and `source_run_id` are that same run id (`_id`, otherwise `id`).

Do not copy `config` except to read `input_archive` and `tool_errors`. Do not copy `shared_with`, `urls`, `user_manual`, `time_saved_per_run`, or `dollar_cost_per_hour`.

## 4. Extract task intent, actions, environment, and outcome

`task_intent` is one source string, redacted: `result.description`, otherwise the document `name`, otherwise `result.name`, otherwise `result.tool_name`. If none of those is a non-empty string, `task_intent` is null. Do not rewrite it into a slug.

`task_summary` stays the joined unique name, description, and tool name so a second source string is not dropped.

`actions` is the ordered list of non-empty step `action` strings after redaction. A step with no action stays in `steps` and is left out of `actions`.

`environment.available_tools` is the unique tool names in first-seen order. A step contributes its action only when the event is `tool_run` or the step has `tool_arguments`, `call_id`, or `tool_result`. User message text is not a tool. `permissions` and `constraints` are null. The traces do not state them. Do not use an empty list, which would mean "none observed" as a positive fact.

`outcome` is the stored status string. Allowed values are `success`, `error`, and `cancelled`, plus `stuck` for `tool_run` only. Do not rename `error` to `failure`. Do not treat a dashboard cost or time field as the outcome.

`bucket_id` is always null. This skill does not assign buckets.

## 5. Missing or ambiguous information

| Situation | Representation |
| --- | --- |
| Optional step field absent on the source | Key omitted. |
| No task text | `task_intent: null`. |
| No tool call observed | `available_tools: []`. |
| Permissions or constraints not stated | `null`, not `[]`. |
| No probability estimates | Step `step_reward: null`, reward status `pending`, probabilities and rationale null. |
| Status missing or blank | Disposition `outcome_unavailable`. Episode is null. Do not emit `outcome: "unknown"`. |
| Status present but not terminal | Disposition `incomplete`. Episode is null. Do not guess success or failure. |
| `file_url` set and body markers absent | Disposition `payload_not_loaded`. |
| Not an execution document, including `datastore_put` | Disposition `unreadable`. |

`warnings` are normalizer notes. They are not a place to store invented facts.

## 6. Step rewards

The reserved method is progress delta: `step_reward = p_after - p_before`. `p_before` and `p_after` are estimates of task-success probability before and after the step. Both must be numbers from 0 to 1.

This formula is a research-inspired proposal. It is not a claim that the code reproduces a paper. It is not a discounted return, a trajectory return, or the verified task outcome. `outcome` stays the stored status even when a step reward is computed.

`normalize_trace` does not read probabilities from the trace. Every step starts as:

```json
{"method": "progress_delta", "p_before": null, "p_after": null, "status": "pending", "rationale": null}
```

with `step_reward` null.

Episode `reward_metadata` is always `{"method": "progress_delta", "status": "pending", "aggregation": "not_defined"}`. No trajectory aggregation formula is defined. Do not sum, average, or discount step rewards into an episode reward.

When a caller has estimates, pass them to `apply_progress_grades(episode, grades)`. Each grade is `{index, p_before, p_after, rationale?}`. The function returns a copy.

- Both probabilities are numbers in [0, 1]: status `computed`, `step_reward` is the difference, and the probabilities are stored. A rationale is stored only when the caller supplied a string, then redacted.
- One probability is missing or null: the step stays `pending`. The supplied number is not stored.
- A probability is a boolean, a non-number, NaN, infinite, or outside [0, 1]: status `rejected`. Reward, probabilities, and rationale are null. The bad values are not stored.
- A grade whose index is not a step, or a grades value that is not a list, changes nothing on the other steps.

## 7. Do not invent rewards or causal claims

Do not fill `p_before`, `p_after`, `step_reward`, or `rationale` from the outcome, the step count, or a hunch about why a step mattered. A rationale that the caller did not write is left null. Rejected grades do not keep the caller's rationale.

## 8. Validate

A normalized episode must satisfy `schema/episode.schema.json` (schema version 2). Required episode fields include `task_intent`, `actions`, `environment`, `outcome`, `steps`, `reward_metadata`, and `bucket_id`. Each step requires `index`, `step_reward`, and `reward_metadata`.

From `trace-normalization`:

```bash
python -B -m unittest discover -s tests -v
```

The tests do not install packages and do not import Autobots.

## 9. Redact

Follow `reference/redaction.md`. Redaction covers step text, tool arguments and results, errors, `task_intent`, `task_summary`, the event error, human-question text, and a grade rationale. It does not rewrite ids, statuses, timestamps, or node ids. Strip a `file_url` query string before storing the URL.

## 10. Inputs that cannot be normalized

`normalize_trace` returns `episode: null` with one of these dispositions:

| disposition | meaning |
| --- | --- |
| `payload_not_loaded` | `file_url` is set and the body markers are absent. |
| `incomplete` | The status is present and is not terminal. |
| `outcome_unavailable` | Status is missing or blank. |
| `unreadable` | Not a run document, not an execution type, or a terminal document with no body and no `file_url`. |

Do not coerce those into an episode. Record a graph or team reader `None`, and the action reader's "payload missing in S3" error, as unresolved retrievals. Do not report them as `normalized`.

## Facts that the code does not infer

- Object key order is the stored order. Context `turn_no` counts per provenance tag, not across the graph.
- Repeated context identities on one node keep the earliest numeric slot. Baseline slot `"0"` comes first.
- When an archive supplies steps, ActionResult timestamps are not merged. The warning says so.
- When `node_vectors` has entries, inner action rows on `output[node]` are not expanded. The warning names the node.

Example files in `examples/` cover a multi-step success, a failed run, a step with no observation, a blank status, a non-agent `datastore_put`, redacted secrets, and pending rewards on every normalized episode. Probability arithmetic is covered by the tests through `apply_progress_grades`, because the traces do not contain estimates.
