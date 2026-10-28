# Autobots trace formats

These notes describe the run documents the normalizer accepts. Paths are inside `autobots-main`. Line numbers refer to that tree and can move; the field names are the contract.

## Where a completed run lives

Every run is an `EventResultDoc` in the Mongo collection `EventResults` (`event_result/event_result_model.py`). The event type is one of:

| `type` | Body model | How the full body is retrieved |
| --- | --- | --- |
| `action_run` | `ActionDoc` inside `result` | Mongo first. If `file_url` is empty, that document is the body. If `file_url` is set, `{run_id}.json` is loaded and only `result` is copied onto the Mongo document. |
| `action_graph_run` | `ActionGraphDoc` inside `result` | `{run_id}.json` first. Empty bytes fall back to Mongo. Any exception returns `None`. |
| `action_team_run` | `ActionTeamDoc` inside `result` | Same S3-then-Mongo pattern. Any exception returns `None`. |
| `tool_run` | `ToolRun` inside `result` | Mongo only, filtered by `type=tool_run`. |

`datastore_put` is a fifth event type. It is not an execution trace. The normalizer rejects it as `unreadable`.

Object keys, from `core/settings.py` and `files/user_files.py`:

- Action runs use folder `action_runs`. The key is `action_runs/{user_id}/{action_run_id}.json`.
- Graph and team runs use folder `runs`. The key is `runs/{user_id}/{run_id}.json`.
- `UserFiles` prefixes the configured folder with the user id. The readers pass filename `{run_id}.json`.

`_with_payload` in `action/action_result/user_action_result.py` states that Mongo is authoritative for everything except `result`, and that S3 holds the full `ActionDoc`. Missing action bytes raise HTTP 404 with detail `Action result payload missing in S3`.

Graph and team getters in `user_action_graph_result.py` and `user_action_team_result.py` log the exception and return `None`, including when the result was not found. A `None` from those readers is an unresolved retrieval. It is not, by itself, a missing run or a loaded trace.

The Mongo projection stored beside a graph object does not carry `output` or `node_vectors` (`action_graph/action_graph/node_result_writer.py`). `ActionLiteDoc` has no `results`, `input`, `output`, or `config`. `ActionTeamLiteDoc` has no `thread` or `results`. `ToolRunLite` has `tool_name` and `tool_args` and omits `output`. A lite action, graph, or team document whose `file_url` is set does not contain the transcript.

## Status

`EventResultStatus` is `success`, `processing`, `error`, `waiting`, `stuck`, `request_cancel`, `cancelled`.

`TERMINAL_STATUSES` in `run_metrics/run_metrics_doc_model.py` is `success`, `error`, `cancelled`. Action, graph, and team runs use that set.

`TERMINAL_TOOL_RUN_STATUSES` in `llm/tools/tool_result/tool_result_doc_model.py` adds `stuck`. A tool run with `stuck` is terminal. An action, graph, or team run with `stuck` is not.

A missing or blank status does not become `success`.

The event error is `error_message: TextObj | None`, and the text is `error_message.text`. An `error` status with no text has no episode error message.

## Action body

`ActionCreate` holds `config`, `results`, `input`, and `output`.

`ActionResult` is one row of `results`: `input`, `output`, `started_at`, `ended_at`, `duration_ms`, `status`, `error`, `attempt`, `turn`. `error` is `TurnError` with `type` and `message`. `turn` is an index on that row. The list order is the order the rows were stored.

`input` and `output` are often DataBlocks: `text`, `urls`, and a server-set `created_at`. Several blocks appear as `blocks: [{text}]` or provider content lists `content: [{text}]`.

`config.input_archive` is optional and specific to OpenAI Responses. `TurnArchiveEntry` in `conn/openai/openai_responses/openai_responses_v2.py` is `turn_number`, `input`, `output`, `in_turn_messages`, and `tool_errors`. `tool_errors` maps a `call_id` to `{type, message}` (`llm/tools/tool_error.py`). Other providers are not assumed to write this archive. When it is absent, `results` or `input`/`output` are the transcript.

`_flatten_archive_turns` walks each turn as `input`, then `in_turn_messages`, then `output`. The chat-history tool skips item types `reasoning` and `compaction`.

Tool-call items seen in that archive use `type` `function_call`, `tool_call`, or `mcp_call`, or an assistant item with `name` and `arguments`. Tool results use `function_call_output`, `tool_result`, or `role: tool`. Arguments are often a JSON string. A result's text is `output`, `content`, or `text`.

`initial_input_snapshot` is the pinned prefix used to rebuild the visible window. The archive already contains the turns. The snapshot is not a second transcript.

## Graph body

`ActionGraphDoc` holds `start_node_id`, `input`, `output`, and `node_vectors`.

`output` is a dict of node id to `ActionDoc`. `node_vectors` is a dict of node id to `NodeContextVector`. The field description says an absent `node_vectors` means a plain DAG, where `output` says everything.

`NodeContextVector.slots` is a dict of slot key to `ContextSlot`. Slot keys are strings because they are document keys. `BASELINE_SLOT` is `"0"`. `ContextSlot.entries` is a list of `ContextEntry`.

`ContextEntry.node_id` is provenance, not the node that owns the vector. `turn_no` counts per `(slot, provenance)` from 0. There is no global lap number (`ContextSlot.next_turn_no`). `identity()` is `(turn_no, node_id)`.

`sort_key(entry, start_node_id)` is `(turn_no, 0 if provenance == start_node_id else 1, provenance)`. The rank exists because a letter start id would otherwise sort after digit node ids.

`node_result_writer.py` stores the vector at `node_vectors[run_ctx.node]` (the executing node) and sets the entry's `node_id` to `run_ctx.provenance_tag`. `entry_from_action_doc` copies that execution's `input` and `output` only. It is one entry per execution, not one entry per `ActionResult`. `seed_all_slots` copies that same entry into every slot of one node's vector.

The episode's `node_id` is the vector key. `provenance_node_id` is `ContextEntry.node_id`.

## Team body

`ThreadEntry` is `member_id`, `action_id`, `action_run_id`, `name`, `role`, `input`, `output`, `started_at`, `ended_at`, `duration_ms`. `role` is `user`, `leader`, or `member`.

`ActionTeamDoc.thread` is the list of those entries. `results` is a list of `ActionTeamResult`, which has only `input` and `output`. `current_active_members` is in-progress state, not a step list.

## Tool body

`ToolRun` is `tool_name`, `tool_args` (a dict), and optional `output` (a dict). A finished tool run may have `output: null`. That is an empty result, not a missing payload.

## Fields kept beside the steps

`human_questions` lives on `EventResultDocCreate`, not inside `result`. Each `HumanQuestion` has `question_id`, `turn_index` (an index into `result.results`), `status` (`pending`, `answered`, `skipped`, `cancelled`), `asked_at`, the question text, and an optional `HumanAnswer` (`selected`, `text`, `urls`, `skipped`, `answered_by`, `answered_at`). The source comment says the question is drawn after that turn's output. The normalizer keeps a compact copy on the episode and does not invent a position inside the turn.

`parent_action_result_id` and `run_kind` (`subagent` or `branch`) are copied onto `source` when they are strings. `queued_inputs` is not a step list. A non-empty value becomes a warning.

`time_saved_per_run` and `dollar_cost_per_hour` exist on action and team documents. They are dashboard inputs. They are not an outcome and are not copied.

## Optional and provider-specific

Not every trace has `input_archive`, `tool_errors`, `node_vectors`, `thread`, `human_questions`, `turn`, `attempt`, or `error`. The normalizer uses a field only when it is present. A graph without `node_vectors` is a DAG. An action without `input_archive` still has a transcript when `results` or `input`/`output` is present. A tool argument string is parsed only when the whole string is a JSON object or array.
