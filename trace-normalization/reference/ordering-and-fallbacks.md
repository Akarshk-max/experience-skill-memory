# Ordering, deduplication, and fallbacks

The stored list or object order is the order. The normalizer does not invent a topological sort or a global clock.

## Action runs

1. If `config.input_archive` is a non-empty list and it yields at least one step, those are the steps.
2. Otherwise use `results` in list order.
3. Otherwise make one step from the action `input` and `output`.

Archive entries sort by `(turn_number, original index)` when `turn_number` is an integer. An entry without `turn_number` uses its original index as that number, so an already sequential archive stays in place. Each turn's messages are `input`, then `in_turn_messages`, then `output`, which is the order in `_flatten_archive_turns`.

Within a turn:

- `reasoning` and `compaction` items are skipped and not copied.
- A tool call opens a step. A later tool result with the same `call_id` or `tool_call_id` fills that step. An unmatched result opens its own step.
- `role` `user` or `system` becomes `action`. `role` `assistant`, or `type: message`, becomes `observation`.
- A message that has text but no known role or type becomes `observation`, and one warning records that this shape was not identified.

`tool_errors[call_id].message` is the step error when that call id is present.

This archive path does not merge `ActionResult` rows. Their `started_at`, `ended_at`, `duration_ms`, `attempt`, and row `status` are therefore absent. A warning says so when `results` was non-empty. This is a limitation, not a claim that those rows were empty.

If the archive yields no steps, the normalizer falls back to `results` and records that fallback.

`turn` on an `ActionResult` is copied to `turn_no`. It is not a sort key. The list order remains the order. Whether a writer can append a row whose `turn` disagrees with its position is not settled by a separate order field; the list is what was stored.

## Graph runs

If any slot has a non-empty `entries` list, the vector transcript is the only step source.

- Nodes follow the key order of `node_vectors`. That is first-write order of the stored object when the object codec preserves keys. It is not a global turn order. `turn_no` is per provenance tag.
- Slots of one node are read in numeric key order, then other keys. `"0"` is the baseline and is read first. This is the read order for deduplication, not the lexicographic order used when `seed_all_slots` first builds the dict.
- Entries with the same `(turn_no, provenance node_id)` on one node keep the first slot. A later copy is dropped and named in `warnings`. `seed_all_slots` writes that duplicate on purpose. Identities are not deduplicated across nodes.
- Remaining entries use `sort_key`: turn, then start-node provenance before any other provenance, then the provenance id. If `start_node_id` is absent, nothing receives the start rank and a warning says so.
- A missing `turn_no` uses the model default `0`, and a warning says the default was used.
- An entry with no provenance `node_id` is skipped.

`output[node].name` may be copied to `action_name`. The output document's `results` and `input_archive` are not expanded in this mode, because `entry_from_action_doc` defines one entry as that execution's input and output, not as one step per inner row. If those inner rows exist, a warning names the node. Their tool calls remain in the source document and are not in the episode. That is an unresolved gap for a later stage, not a silent drop.

The graph writer treats `output` and `node_vectors` as covering the same nodes. A node that appears only in `output` is not emitted, and a warning names it. A node that appears only in `node_vectors` keeps its entry transcript, and a warning says the action name was unavailable.

If `node_vectors` is missing, or present with no entries, steps come from `output` in stored key order. Each value is normalized as an action document, so a node that itself has an archive or `results` expands. A warning records the empty-vector fallback. An output value that is not an object is skipped.

## Team runs

`thread` is walked in list order. Each entry keeps `role`, `name` as `action_name`, `member_id`, `action_id`, and `action_run_id`. Input text is `action`. Output text is `observation`. `started_at` is the timestamp when present.

If the thread is absent, empty, or yields no steps, `results` is used in list order. `ActionTeamResult` has input and output only, so those steps have no role and no timing. If that also yields nothing, one step is made from the team `input` and `output`.

`current_active_members` is not turned into steps. A non-empty list is a warning.

## Tool runs

One step. `tool_args` is copied only when it is a non-empty object. `output` may be null. The step timestamp is the event `created_at` when that is a string or datetime. Tool runs have no archive and no thread.

## Human questions

`human_questions` stay on the episode. `turn_index` is copied so a later stage can place them after that result row. Splicing them into `steps` would invent an offset inside the turn. Option descriptions, answer urls, and `answered_by` are not copied.

## Empty and unreadable bodies

A full action document includes `results` even when the list is empty. An empty loaded body normalizes to an episode with `steps: []`.

A terminal document with `file_url` and none of the body markers is `payload_not_loaded`. Markers are:

- action: `results`, `input`, `output`, or `config.input_archive`
- graph: `output` or `node_vectors`
- team: `thread` or `results`
- tool: a non-empty `tool_name` (tools do not use `file_url` to load a body)

A terminal document with no `file_url` and none of those markers is `unreadable`. A non-terminal status is `incomplete` even when the body is also absent; the detail says the payload was not on the document when that is true.

## What the episode does not decide

The normalizer does not repair a graph or team `None` from a swallowed exception. The caller has no document to pass. It does not fetch the object named by `file_url`. It does not treat `queued_inputs` as work that still ran. It reserves `step_reward` as null and does not assign a value. See `reference/rewards.md`.
