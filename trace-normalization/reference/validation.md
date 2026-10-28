# Validation

`normalize_trace` either returns one episode or rejects the document. It never returns an episode whose payload was not on the document.

## Dispositions

| disposition | When | episode |
| --- | --- | --- |
| `normalized` | Status is terminal for the event type, and the body markers are present. | Schema version 2 episode. |
| `payload_not_loaded` | Status is terminal, `file_url` is set, and the body markers are absent. | `null` |
| `incomplete` | Status is a non-empty string and is not terminal for that type. | `null` |
| `outcome_unavailable` | `status` is missing or blank. | `null` |
| `unreadable` | Not an object, no string id, no type, a type other than the four execution types, a non-string status, or a terminal body with no markers and no `file_url`. | `null` |

Terminal statuses:

- `action_run`, `action_graph_run`, `action_team_run`: `success`, `error`, `cancelled`
- `tool_run`: those three, plus `stuck`

`processing`, `waiting`, `request_cancel`, and `stuck` on a non-tool run are `incomplete`.

## Body markers

The markers mean the detailed body is on this document. They do not mean the caller successfully downloaded it. The caller must only pass an action, graph, or team document after the reader has merged or returned the full body.

- Action: key `results`, `input`, or `output`, or key `config.input_archive`.
- Graph: key `output` or `node_vectors`.
- Team: key `thread` or `results`.
- Tool: non-empty string `tool_name`. `output` may be null. `file_url` is not a tool-run load path; if one is present it is provenance only, with a warning.

An empty `results` list still counts as loaded. The episode then has no steps, or only the steps that the input and output fields produce when the result rows themselves are empty.

## Episode checks

A normalized episode must satisfy `schema/episode.schema.json`.

- `episode_id` and `source.source_run_id` equal the document `_id` or, if that is not a non-empty string, `id`.
- `source.collection` is `EventResults`.
- `schema_version` is `2`.
- `outcome` is the status string, unchanged. Missing or blank status does not become an episode with outcome `unknown`.
- `task_intent` is `result.description`, otherwise the document `name`, otherwise `result.name`, otherwise `result.tool_name`, otherwise null.
- `actions` lists step `action` values in index order. Steps with no action are omitted from this list.
- `environment.permissions` and `environment.constraints` are null.
- `bucket_id` is null. Normalization does not assign a bucket.
- `steps[i].index` is `i`, starting at 0, with no gaps. There is no separate `step_id`.
- Every step has `step_reward: null` and reward status `pending` until `apply_progress_grades` accepts estimates. See `reference/rewards.md`.
- Episode `reward_metadata.aggregation` is `not_defined`.
- `error_message` is omitted when the source had none. An error status does not create one.
- `warnings` is always a list. An empty list means the normalizer added no notes.
- No field named `reward`, `score`, `step_value`, `advantage`, or `return`. The reserved name is `step_reward`.

`human_questions` is omitted when the source list was missing or empty. A question without text is skipped.

## Retrieval the skill does not classify

These stay outside the function because there is no document to validate:

- The action reader raised `Action result payload missing in S3`.
- The graph or team reader returned `None` after an exception. That `None` covers both a missing row and a failed read.
- The caller has a `file_url` and has not fetched the object yet.

Record those as unresolved retrievals. Do not report them as `normalized`.

## Independent test

From `Write Path/trace-normalization`:

```bash
python -B -m unittest discover -s tests -v
```

The tests use the example documents in `examples/`. They check dispositions, order, redaction, schema shape, pending rewards, and progress-delta arithmetic. They do not contact a database, object storage, or a model provider.

Example coverage:

| Case | File |
| --- | --- |
| Successful multi-step run | `action_archive` |
| Failed run | `action_results`, `action_error_without_message` |
| Missing observation | `action_results` second step |
| Unknown outcome | `action_blank_status` (`outcome_unavailable`, no episode) |
| Non-terminal status | `action_processing`, `action_stuck` |
| Non-agent event | `datastore_put` |
| Redaction | `action_archive`, `tool_run`, `action_human_question` |
| No reward estimates | Every `normalized` output |
