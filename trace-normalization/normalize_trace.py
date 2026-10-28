"""Turn one completed Autobots run document into an ordered episode.

The rules are the Trace Normalization Skill. This module is the executable
contract: it imports only the Python standard library, calls no model provider,
and does not read MongoDB or object storage. A caller passes a document it has
already retrieved. A missing detailed payload stays a failed retrieval.

Source of the shapes this accepts: the autobots-main tree, in particular
event_result_model, the four run readers, action/graph/team/tool documents,
context_vector, node_result_writer, TurnArchiveEntry, and the two redaction
helpers named in reference/redaction.md.
"""

from __future__ import annotations

import copy
import json
import math
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SCHEMA_VERSION = 2
PROGRESS_DELTA = "progress_delta"
REWARD_PENDING = "pending"
REWARD_COMPUTED = "computed"
REWARD_REJECTED = "rejected"
AGGREGATION_NOT_DEFINED = "not_defined"
COLLECTION = "EventResults"

ACTION_RUN = "action_run"
GRAPH_RUN = "action_graph_run"
TEAM_RUN = "action_team_run"
TOOL_RUN = "tool_run"
EXECUTION_TYPES = (ACTION_RUN, GRAPH_RUN, TEAM_RUN, TOOL_RUN)

RUN_TERMINAL = ("success", "error", "cancelled")
TOOL_TERMINAL = ("success", "error", "cancelled", "stuck")

NORMALIZED = "normalized"
PAYLOAD_NOT_LOADED = "payload_not_loaded"
INCOMPLETE = "incomplete"
OUTCOME_UNAVAILABLE = "outcome_unavailable"
UNREADABLE = "unreadable"

SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "code",
        "id_token",
        "basic_token",
        "api_key",
        "management_api_key",
        "consumer_key",
        "consumer_secret",
        "token_secret",
        "client_secret",
        "password",
        "private_key",
        "ssl_cert_path",
        "ssl_key_path",
        "fb_exchange_token",
        "token",
        "bearer_token",
        "csrf_token",
        "user_token",
        "app_key",
        "license_key",
        "secret",
        "auth_code",
        "service_account_json",
        "incoming_webhook",
        "aws_access_key_id",
        "aws_secret_access_key",
        "private_key_path",
        "public_certificate",
        "connection_string",
        "credentials_info",
        "link_token_hash",
        "external_user_id",
        "external_chat_id",
        "external_username",
        "telegram_user_id",
        "telegram_chat_id",
        "telegram_username",
    }
)

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password)\b\s*[:=]\s*([^\s,;]+)"
    ),
    re.compile(r"(?i)\b(bearer)\s+([a-z0-9\-\._=]+)"),
)

_SKIP_MESSAGE_TYPES = frozenset({"reasoning", "compaction"})
_TOOL_CALL_TYPES = frozenset({"function_call", "tool_call", "mcp_call"})
_TOOL_RESULT_TYPES = frozenset({"function_call_output", "tool_result"})
_PAYLOAD_DROP_KEYS = frozenset(
    {
        "config",
        "shared_with",
        "urls",
        "user_manual",
        "time_saved_per_run",
        "dollar_cost_per_hour",
    }
)
_CONTENT_FIELDS = (
    "action",
    "observation",
    "tool_arguments",
    "tool_result",
    "error",
    "action_name",
)
_URLS_WARNING = "A block had urls and no text. Urls were not copied."
_UNKNOWN_MESSAGE_WARNING = (
    "A message without a known role or type was stored as an observation."
)


def normalize_trace(document: Any) -> dict[str, Any]:
    """Normalize one run document.

    Returns disposition, detail, and episode. episode is present only when
    disposition is "normalized". Other dispositions mean no episode was produced.
    """
    if not isinstance(document, dict):
        return _rejected(UNREADABLE, "The trace is not an object.")

    run_id = _string(document.get("_id")) or _string(document.get("id"))
    if run_id is None:
        return _rejected(UNREADABLE, "The document has no string id.")

    event_type = _string(document.get("type"))
    if event_type is None:
        return _rejected(UNREADABLE, "The document has no event type.")
    if event_type not in EXECUTION_TYPES:
        return _rejected(
            UNREADABLE, f"Event type {event_type!r} is not an execution trace."
        )

    status = document.get("status")
    if status is None or (isinstance(status, str) and not status.strip()):
        return _rejected(
            OUTCOME_UNAVAILABLE,
            "The document has no status, so no outcome was recorded.",
        )
    if not isinstance(status, str):
        return _rejected(UNREADABLE, "The status is not a string.")
    status = status.strip()

    result = document.get("result")
    if not isinstance(result, dict):
        result = {}
    file_url, query_removed = _file_url(document.get("file_url"))
    loaded = _body_loaded(event_type, result)
    terminal = TOOL_TERMINAL if event_type == TOOL_RUN else RUN_TERMINAL
    if status not in terminal:
        detail = f"Status {status} is not terminal for {event_type}."
        if file_url and not loaded:
            detail += " The detailed payload was not on this document."
        return _rejected(INCOMPLETE, detail)
    if not loaded:
        if file_url:
            return _rejected(
                PAYLOAD_NOT_LOADED,
                "file_url is set, but the detailed trace payload is not on this "
                "document. It was not treated as loaded.",
            )
        return _rejected(UNREADABLE, _missing_body_detail(event_type))

    warnings: list[str] = []
    if query_removed:
        warnings.append("The file_url query string was removed before it was stored.")
    if event_type == TOOL_RUN and file_url:
        warnings.append(
            "A tool_run is read from Mongo only. file_url was kept as provenance "
            "and was not used to load another payload."
        )
    _note_side_channels(document, result, warnings)

    if event_type == ACTION_RUN:
        steps = steps_from_action_document(result, warnings)
    elif event_type == GRAPH_RUN:
        steps = steps_from_graph(result, warnings)
    elif event_type == TEAM_RUN:
        steps = steps_from_team(result, warnings)
    else:
        tool_steps = steps_from_tool(result, _as_iso(document.get("created_at")), warnings)
        if tool_steps is None:
            return _rejected(UNREADABLE, "The tool document has no tool_name.")
        steps = tool_steps

    steps = _finish_steps(steps)
    episode = _episode(
        document=document,
        result=result,
        run_id=run_id,
        event_type=event_type,
        status=status,
        file_url=file_url,
        steps=steps,
        warnings=warnings,
    )
    return {"disposition": NORMALIZED, "detail": "Normalized.", "episode": episode}


def steps_from_action_document(result: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    config = result.get("config")
    archive = None
    if isinstance(config, dict) and isinstance(config.get("input_archive"), list):
        archive = config.get("input_archive")
    if archive:
        steps = steps_from_archive(archive, warnings)
        if steps:
            results = result.get("results")
            if isinstance(results, list) and results:
                warnings.append(
                    "input_archive supplied the steps. ActionResult rows were not "
                    "merged, so their timestamps, attempt, and turn status are not "
                    "on these steps."
                )
            return steps
        warnings.append("input_archive produced no steps. Fell back to ActionResult rows.")

    results = result.get("results")
    if isinstance(results, list) and results:
        steps: list[dict[str, Any]] = []
        for row in results:
            steps.extend(steps_from_result_row(row, warnings))
        if steps:
            return steps
        warnings.append("ActionResult rows produced no steps. Fell back to input and output.")
    return steps_from_result_row(
        {"input": result.get("input"), "output": result.get("output")}, warnings
    )


def steps_from_archive(archive: list[Any], warnings: list[str]) -> list[dict[str, Any]]:
    ordered: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for index, entry in enumerate(archive):
        if not isinstance(entry, dict):
            warnings.append("Skipped an input_archive entry that was not an object.")
            continue
        turn = entry.get("turn_number")
        primary = turn if _is_int(turn) else index
        ordered.append(((primary, index), entry))
    ordered.sort(key=lambda item: item[0])

    steps: list[dict[str, Any]] = []
    for _, entry in ordered:
        turn_no = entry.get("turn_number") if _is_int(entry.get("turn_number")) else None
        tool_errors = entry.get("tool_errors")
        if not isinstance(tool_errors, dict):
            tool_errors = {}
        pending: dict[str, dict[str, Any]] = {}
        for message in _archive_messages(entry):
            message_type = message.get("type")
            if message_type in _SKIP_MESSAGE_TYPES:
                continue
            if _is_tool_call(message):
                step: dict[str, Any] = {}
                _put(step, "turn_no", turn_no)
                _put(step, "action", _string(message.get("name")) or _string(message.get("tool_name")))
                call_id = _string(message.get("call_id")) or _string(message.get("tool_call_id")) or _string(message.get("id"))
                _put(step, "call_id", call_id)
                arguments = message.get("arguments", message.get("args"))
                if arguments not in (None, "", {}, []):
                    step["tool_arguments"] = arguments
                if call_id and isinstance(tool_errors.get(call_id), dict):
                    _put(step, "error", _string(tool_errors[call_id].get("message")))
                _put(step, "timestamp", _message_time(message))
                steps.append(step)
                if call_id:
                    pending[call_id] = step
                continue
            if _is_tool_result(message):
                call_id = _string(message.get("call_id")) or _string(message.get("tool_call_id"))
                target = pending.get(call_id) if call_id else None
                if target is None:
                    target = {}
                    _put(target, "turn_no", turn_no)
                    _put(target, "call_id", call_id)
                    _put(target, "timestamp", _message_time(message))
                    steps.append(target)
                result_text = _tool_output_text(message)
                if result_text and "tool_result" not in target:
                    target["tool_result"] = result_text
                continue
            text = text_of(message)
            if text is None:
                _note_urls(message, warnings)
            step = {}
            _put(step, "turn_no", turn_no)
            _put(step, "timestamp", _message_time(message))
            role = message.get("role")
            if role in ("user", "system"):
                _put(step, "action", text)
            elif role == "assistant" or message_type == "message":
                _put(step, "observation", text)
            elif text:
                _put(step, "observation", text)
                if _UNKNOWN_MESSAGE_WARNING not in warnings:
                    warnings.append(_UNKNOWN_MESSAGE_WARNING)
            if _keep(step):
                steps.append(step)
    return [step for step in steps if _keep(step)]


def steps_from_graph(result: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    vectors = result.get("node_vectors") if isinstance(result.get("node_vectors"), dict) else None
    if vectors is not None and _vectors_have_entries(vectors):
        start = _string(result.get("start_node_id"))
        if start is None:
            warnings.append(
                "start_node_id is absent, so context entries were not ranked as a start node."
            )
        steps: list[dict[str, Any]] = []
        produced: set[str] = set()
        for node_id, vector in vectors.items():
            node_key = str(node_id)
            node_doc = output.get(node_id)
            if output and node_key not in {str(key) for key in output}:
                warnings.append(
                    f"Graph node {node_key} is in node_vectors but not in output. "
                    "The entry transcript was kept. The action name was not available."
                )
            node_steps = _steps_from_vector(node_key, vector, start, node_doc, warnings)
            if node_steps:
                produced.add(node_key)
                steps.extend(node_steps)
            else:
                warnings.append(
                    f"Graph node {node_key} has a context vector but produced no steps."
                )
        for node_id in output:
            if str(node_id) not in {str(key) for key in vectors}:
                warnings.append(
                    f"Graph node {node_id} is in output but not in node_vectors. "
                    "It was not emitted, because a populated node_vectors transcript is the step source."
                )
        return steps
    if vectors is not None:
        warnings.append("node_vectors is present but has no entries. Steps were taken from output.")
    return _steps_from_graph_output(output, warnings)


def steps_from_team(result: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    thread = result.get("thread")
    if isinstance(thread, list) and thread:
        steps: list[dict[str, Any]] = []
        for entry in thread:
            if not isinstance(entry, dict):
                warnings.append("Skipped a thread entry that was not an object.")
                continue
            step: dict[str, Any] = {}
            _put(step, "action", payload_text(entry.get("input")))
            _put(step, "observation", payload_text(entry.get("output")))
            _note_urls(entry.get("input"), warnings)
            _note_urls(entry.get("output"), warnings)
            _put(step, "action_name", _string(entry.get("name")))
            _put(step, "role", _string(entry.get("role")))
            _put(step, "member_id", _string(entry.get("member_id")))
            _put(step, "action_id", _string(entry.get("action_id")))
            _put(step, "action_run_id", _string(entry.get("action_run_id")))
            started = _as_iso(entry.get("started_at"))
            ended = _as_iso(entry.get("ended_at"))
            _put(step, "started_at", started)
            _put(step, "ended_at", ended)
            _put(step, "timestamp", started or ended)
            if _is_number(entry.get("duration_ms")):
                step["duration_ms"] = entry["duration_ms"]
            if _keep(step):
                steps.append(step)
            else:
                warnings.append("Skipped an empty thread entry.")
        if steps:
            return steps
        warnings.append("thread produced no steps. Fell back to team results.")

    results = result.get("results")
    if isinstance(results, list) and results:
        steps = []
        for row in results:
            steps.extend(steps_from_result_row(row, warnings))
        if steps:
            return steps
    return steps_from_result_row(
        {"input": result.get("input"), "output": result.get("output")}, warnings
    )


def steps_from_tool(
    result: dict[str, Any], created_at: str | None, warnings: list[str]
) -> list[dict[str, Any]] | None:
    name = _string(result.get("tool_name"))
    if name is None:
        return None
    step: dict[str, Any] = {"action": name}
    arguments = result.get("tool_args")
    if isinstance(arguments, dict) and arguments:
        step["tool_arguments"] = arguments
    elif arguments not in (None, {}, []):
        warnings.append("tool_args was not an object and was not copied.")
    text = payload_text(result.get("output"))
    if text:
        step["tool_result"] = text
    _note_urls(result.get("output"), warnings)
    _put(step, "timestamp", created_at)
    return [step]


def steps_from_result_row(row: Any, warnings: list[str]) -> list[dict[str, Any]]:
    if not isinstance(row, dict):
        warnings.append("Skipped a result row that was not an object.")
        return []
    step: dict[str, Any] = {}
    _put(step, "action", payload_text(row.get("input")))
    _put(step, "observation", payload_text(row.get("output")))
    _note_urls(row.get("input"), warnings)
    _note_urls(row.get("output"), warnings)
    error = row.get("error")
    if isinstance(error, dict):
        message = _string(error.get("message"))
        _put(step, "error", message or _string(error.get("type")))
    elif _string(error):
        _put(step, "error", _string(error))
    _put(step, "turn_no", row.get("turn") if _is_int(row.get("turn")) else None)
    _put(step, "attempt", row.get("attempt") if _is_int(row.get("attempt")) else None)
    _put(step, "step_status", _string(row.get("status")))
    started = _as_iso(row.get("started_at"))
    ended = _as_iso(row.get("ended_at"))
    _put(step, "started_at", started)
    _put(step, "ended_at", ended)
    _put(step, "timestamp", started or ended or _block_time(row.get("input")) or _block_time(row.get("output")))
    if _is_number(row.get("duration_ms")):
        step["duration_ms"] = row["duration_ms"]
    if _keep(step):
        return [step]
    return []


def text_of(value: Any, depth: int = 0) -> str | None:
    if depth > 6 or value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        parts = [text_of(item, depth + 1) for item in value]
        joined = "\n".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        own = value.get("text")
        if isinstance(own, str) and own.strip():
            return own.strip()
        for key in ("blocks", "content", "output"):
            if key in value and value[key] not in (None, "", [], {}):
                found = text_of(value[key], depth + 1)
                if found:
                    return found
    return None


def payload_text(value: Any) -> str | None:
    text = text_of(value)
    if text:
        return text
    reduced = _drop_payload_keys(value)
    if isinstance(reduced, (dict, list)) and reduced not in ({}, []):
        return json.dumps(reduced, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return None


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: redact(item)
            for key, item in value.items()
            if isinstance(key, str) and key not in SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        parsed = _json_container(value)
        if parsed is not None:
            return json.dumps(
                redact(parsed), sort_keys=True, ensure_ascii=False, separators=(",", ":")
            )
        return _redact_text(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _episode(
    *,
    document: dict[str, Any],
    result: dict[str, Any],
    run_id: str,
    event_type: str,
    status: str,
    file_url: str | None,
    steps: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "collection": COLLECTION,
        "source_run_id": run_id,
        "event_type": event_type,
    }
    _put(source, "user_id", _string(document.get("user_id")))
    _put(source, "file_url", file_url)
    _put(source, "parent_action_result_id", _string(document.get("parent_action_result_id")))
    _put(source, "run_kind", _string(document.get("run_kind")))

    episode: dict[str, Any] = {
        "episode_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "source_run_id": run_id,
        "event_type": event_type,
        "source": source,
        "task_intent": _redact_text_field(_task_intent(document, result)),
        "actions": [step["action"] for step in steps if isinstance(step.get("action"), str)],
        "environment": {
            "available_tools": _available_tools(steps, event_type),
            "permissions": None,
            "constraints": None,
        },
        "outcome": status,
        "steps": steps,
        "reward_metadata": _episode_reward_metadata(),
        "bucket_id": None,
        "warnings": warnings,
    }
    summary = _task_summary(document, result)
    if summary:
        redacted = _redact_text_field(summary)
        if redacted:
            episode["task_summary"] = redacted
    error_message = _error_message(document.get("error_message"))
    if error_message:
        redacted = _redact_text_field(error_message)
        if redacted:
            episode["error_message"] = redacted
    _put(episode, "source_created_at", _as_iso(document.get("created_at")))
    _put(episode, "source_updated_at", _as_iso(document.get("updated_at")))
    questions = _human_questions(document.get("human_questions"))
    if questions:
        episode["human_questions"] = questions
    return episode


def _finish_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    finished: list[dict[str, Any]] = []
    for step in steps:
        cleaned: dict[str, Any] = {}
        for key, value in step.items():
            if key in ("action", "observation", "tool_result", "error", "action_name"):
                redacted = _redact_text_field(value)
                if redacted is not None:
                    cleaned[key] = redacted
            elif key == "tool_arguments":
                redacted = _redact_arguments(value)
                if redacted not in (None, {}, [], ""):
                    cleaned[key] = redacted
            else:
                cleaned[key] = value
        if _keep(cleaned):
            finished.append(cleaned)
    for index, step in enumerate(finished):
        step["index"] = index
        step["step_reward"] = None
        step["reward_metadata"] = _pending_step_reward()
    return finished


def _steps_from_vector(
    node_id: str,
    vector: Any,
    start_node_id: str | None,
    node_doc: Any,
    warnings: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(vector, dict):
        warnings.append(f"Graph node {node_id} has a context vector that is not an object.")
        return []
    slots = vector.get("slots")
    if not isinstance(slots, dict):
        return []
    chosen: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    missing_turn = False
    for slot_key in sorted(slots, key=_slot_sort_key):
        slot = slots[slot_key]
        entries = slot.get("entries") if isinstance(slot, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                warnings.append(f"Skipped a context entry on node {node_id} that was not an object.")
                continue
            provenance = _string(entry.get("node_id"))
            if provenance is None:
                warnings.append(f"Skipped a context entry on node {node_id} with no provenance node_id.")
                continue
            if "turn_no" not in entry:
                missing_turn = True
            turn_no = entry.get("turn_no") if _is_int(entry.get("turn_no")) else 0
            identity = (turn_no, provenance)
            if identity in seen:
                warnings.append(
                    f"Dropped a repeated context entry on node {node_id} "
                    f"for turn {turn_no} from {provenance}."
                )
                continue
            seen.add(identity)
            chosen.append(entry)
    if missing_turn:
        warnings.append(
            f"A context entry on node {node_id} omitted turn_no. The model default 0 was used."
        )
    chosen.sort(key=lambda entry: _context_sort_key(entry, start_node_id))
    action_name = _string(node_doc.get("name")) if isinstance(node_doc, dict) else None
    if isinstance(node_doc, dict) and _action_has_inner_transcript(node_doc):
        warnings.append(
            f"Node {node_id} output contains results or an input_archive. Those inner rows "
            "were not expanded, because each context entry is one input/output for that execution."
        )
    steps: list[dict[str, Any]] = []
    for entry in chosen:
        step: dict[str, Any] = {"node_id": node_id}
        _put(step, "provenance_node_id", _string(entry.get("node_id")))
        turn_no = entry.get("turn_no") if _is_int(entry.get("turn_no")) else 0
        step["turn_no"] = turn_no
        _put(step, "action", payload_text(entry.get("input")))
        _put(step, "observation", payload_text(entry.get("output")))
        _note_urls(entry.get("input"), warnings)
        _note_urls(entry.get("output"), warnings)
        _put(step, "action_name", action_name)
        _put(step, "timestamp", _block_time(entry.get("input")) or _block_time(entry.get("output")))
        if _keep(step):
            steps.append(step)
    return steps


def _steps_from_graph_output(output: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for node_id, node_doc in output.items():
        node_key = str(node_id)
        if not isinstance(node_doc, dict):
            warnings.append(f"Skipped graph output node {node_key} because it was not an object.")
            continue
        node_steps = steps_from_action_document(node_doc, warnings)
        if not node_steps:
            warnings.append(f"Graph node {node_key} produced no steps.")
            continue
        action_name = _string(node_doc.get("name"))
        for step in node_steps:
            step["node_id"] = node_key
            _put(step, "action_name", action_name)
        steps.extend(node_steps)
    return steps


def _body_loaded(event_type: str, result: dict[str, Any]) -> bool:
    if event_type == ACTION_RUN:
        if any(key in result for key in ("results", "input", "output")):
            return True
        config = result.get("config")
        return isinstance(config, dict) and "input_archive" in config
    if event_type == GRAPH_RUN:
        return "output" in result or "node_vectors" in result
    if event_type == TEAM_RUN:
        return "thread" in result or "results" in result
    return _string(result.get("tool_name")) is not None


def _missing_body_detail(event_type: str) -> str:
    if event_type == ACTION_RUN:
        return (
            "The action document has no results, input, output, or input_archive, and no file_url."
        )
    if event_type == GRAPH_RUN:
        return "The graph document has no output or node_vectors, and no file_url."
    if event_type == TEAM_RUN:
        return "The team document has no thread or results, and no file_url."
    return "The tool document has no tool_name."


def _vectors_have_entries(vectors: dict[str, Any]) -> bool:
    for vector in vectors.values():
        if not isinstance(vector, dict) or not isinstance(vector.get("slots"), dict):
            continue
        for slot in vector["slots"].values():
            if isinstance(slot, dict) and isinstance(slot.get("entries"), list) and slot["entries"]:
                return True
    return False


def _action_has_inner_transcript(node_doc: dict[str, Any]) -> bool:
    results = node_doc.get("results")
    if isinstance(results, list) and results:
        return True
    config = node_doc.get("config")
    archive = config.get("input_archive") if isinstance(config, dict) else None
    return isinstance(archive, list) and bool(archive)


def _note_side_channels(document: dict[str, Any], result: dict[str, Any], warnings: list[str]) -> None:
    queued = document.get("queued_inputs")
    if isinstance(queued, (dict, list)) and queued:
        warnings.append("queued_inputs was not converted into steps.")
    active = result.get("current_active_members")
    if isinstance(active, list) and active:
        warnings.append("current_active_members was not converted into steps.")


def _human_questions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    questions: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        question = _string(item.get("question"))
        if question is None:
            continue
        record: dict[str, Any] = {}
        _put(record, "question_id", _string(item.get("question_id")))
        if _is_int(item.get("turn_index")):
            record["turn_index"] = item["turn_index"]
        _put(record, "status", _string(item.get("status")))
        redacted_question = _redact_text_field(question)
        if redacted_question:
            record["question"] = redacted_question
        _put(record, "asked_at", _as_iso(item.get("asked_at")))
        answer = item.get("answer")
        if isinstance(answer, dict):
            answer_text = _string(answer.get("text"))
            if answer_text:
                redacted_answer = _redact_text_field(answer_text)
                if redacted_answer:
                    record["answer_text"] = redacted_answer
            selected = answer.get("selected")
            if isinstance(selected, list):
                labels = [_string(label) for label in selected]
                labels = [label for label in labels if label]
                if labels:
                    record["answer_selected"] = labels
            if isinstance(answer.get("skipped"), bool):
                record["answer_skipped"] = answer["skipped"]
            _put(record, "answered_at", _as_iso(answer.get("answered_at")))
        if record.get("question"):
            questions.append(record)
    return questions


def apply_progress_grades(episode: dict[str, Any], grades: Any) -> dict[str, Any]:
    """Fill step rewards from supplied probability estimates.

    Normalization never calls this. A grade is not read from the trace.
    `step_reward = p_after - p_before` only when both values are numbers in
    [0, 1]. Anything else leaves that step unset. This does not compute a
    trajectory reward; episode aggregation stays `not_defined`.
    """
    updated = copy.deepcopy(episode)
    if not isinstance(grades, list):
        return updated
    by_index: dict[int, dict[str, Any]] = {}
    for item in grades:
        if isinstance(item, dict) and _is_int(item.get("index")):
            by_index[item["index"]] = item
    for step in updated.get("steps") or []:
        grade = by_index.get(step.get("index"))
        if grade is None:
            continue
        status, reward, before, after, rationale = _interpret_grade(grade)
        step["step_reward"] = reward
        step["reward_metadata"] = {
            "method": PROGRESS_DELTA,
            "p_before": before,
            "p_after": after,
            "status": status,
            "rationale": rationale,
        }
    updated["reward_metadata"] = _episode_reward_metadata()
    updated["bucket_id"] = None
    return updated


def _interpret_grade(
    grade: dict[str, Any],
) -> tuple[str, float | None, float | None, float | None, str | None]:
    before_present = "p_before" in grade and grade.get("p_before") is not None
    after_present = "p_after" in grade and grade.get("p_after") is not None
    if not before_present or not after_present:
        return REWARD_PENDING, None, None, None, None
    before = _probability(grade.get("p_before"))
    after = _probability(grade.get("p_after"))
    if before is None or after is None:
        return REWARD_REJECTED, None, None, None, None
    rationale = grade.get("rationale")
    text = _redact_text_field(rationale) if isinstance(rationale, str) else None
    return REWARD_COMPUTED, after - before, before, after, text


def _probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if 0 <= value <= 1:
        return float(value)
    return None


def _pending_step_reward() -> dict[str, Any]:
    return {
        "method": PROGRESS_DELTA,
        "p_before": None,
        "p_after": None,
        "status": REWARD_PENDING,
        "rationale": None,
    }


def _episode_reward_metadata() -> dict[str, Any]:
    return {
        "method": PROGRESS_DELTA,
        "status": REWARD_PENDING,
        "aggregation": AGGREGATION_NOT_DEFINED,
    }


def _task_intent(document: dict[str, Any], result: dict[str, Any]) -> str | None:
    """One source string for the task, not an inferred label.

    Description is the problem statement when the document has one. Otherwise
    the run name, then the tool name. No text means the intent is unknown.
    """
    for value in (
        result.get("description"),
        document.get("name"),
        result.get("name"),
        result.get("tool_name"),
    ):
        text = _string(value)
        if text:
            return text
    return None


def _available_tools(steps: list[dict[str, Any]], event_type: str) -> list[str]:
    tools: list[str] = []
    for step in steps:
        name = step.get("action")
        if not isinstance(name, str):
            continue
        observed = event_type == TOOL_RUN or any(
            key in step for key in ("tool_arguments", "call_id", "tool_result")
        )
        if observed and name not in tools:
            tools.append(name)
    return tools


def _task_summary(document: dict[str, Any], result: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for value in (
        document.get("name"),
        result.get("name"),
        result.get("description"),
        result.get("tool_name"),
    ):
        text = _string(value)
        if text and text not in parts:
            parts.append(text)
    return "\n".join(parts) or None


def _error_message(value: Any) -> str | None:
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, dict):
        return _string(value.get("text"))
    return None


def _archive_messages(entry: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for bucket in ("input", "in_turn_messages", "output"):
        items = entry.get(bucket)
        if not isinstance(items, list):
            continue
        messages.extend(item for item in items if isinstance(item, dict))
    return messages


def _is_tool_call(message: dict[str, Any]) -> bool:
    message_type = message.get("type")
    if message_type in _TOOL_CALL_TYPES:
        return True
    if message_type == "message":
        return False
    return (
        message.get("role") == "assistant"
        and bool(_string(message.get("name")) or _string(message.get("tool_name")))
        and ("arguments" in message or "args" in message)
    )


def _is_tool_result(message: dict[str, Any]) -> bool:
    if message.get("type") in _TOOL_RESULT_TYPES:
        return True
    return message.get("role") == "tool"


def _tool_output_text(message: dict[str, Any]) -> str | None:
    for key in ("output", "content", "text"):
        if key in message:
            text = payload_text(message.get(key))
            if text:
                return text
    return None


def _redact_arguments(value: Any) -> Any:
    if isinstance(value, str):
        parsed = _json_container(value)
        if parsed is not None:
            return redact(parsed)
    return redact(value)


def _redact_text_field(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        redacted = redact(value)
        if redacted in ({}, []):
            return None
        return json.dumps(redacted, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, str):
        redacted = redact(value)
        if isinstance(redacted, str) and redacted.strip():
            return redacted
        return None
    redacted = redact(value)
    if isinstance(redacted, str) and redacted.strip():
        return redacted
    return None


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}: ***REDACTED***", redacted)
    return redacted


def _json_container(value: str) -> Any | None:
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, (dict, list)):
        return parsed
    return None


def _file_url(value: Any) -> tuple[str | None, bool]:
    text = _string(value)
    if text is None:
        return None, False
    parts = urlsplit(text)
    if not parts.query:
        return text, False
    cleaned = urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    return cleaned, True


def _context_sort_key(entry: dict[str, Any], start_node_id: str | None) -> tuple[int, int, str]:
    provenance = _string(entry.get("node_id")) or ""
    turn_no = entry.get("turn_no") if _is_int(entry.get("turn_no")) else 0
    is_start = start_node_id is not None and provenance == start_node_id
    return (turn_no, 0 if is_start else 1, provenance)


def _slot_sort_key(key: Any) -> tuple[int, int, str]:
    if isinstance(key, bool):
        return (1, 0, str(key))
    if isinstance(key, int):
        return (0, key, "")
    text = str(key)
    try:
        return (0, int(text), "")
    except ValueError:
        return (1, 0, text)


def _drop_payload_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_payload_keys(item)
            for key, item in value.items()
            if key not in _PAYLOAD_DROP_KEYS
        }
    if isinstance(value, list):
        return [_drop_payload_keys(item) for item in value]
    return value


def _has_urls(value: Any, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if isinstance(value, dict):
        urls = value.get("urls")
        if isinstance(urls, list) and any(_string(url) for url in urls):
            return True
        for key in ("blocks", "content"):
            if isinstance(value.get(key), list) and any(
                _has_urls(item, depth + 1) for item in value[key]
            ):
                return True
    return False


def _note_urls(value: Any, warnings: list[str]) -> None:
    if text_of(value) is None and _has_urls(value) and _URLS_WARNING not in warnings:
        warnings.append(_URLS_WARNING)


def _block_time(value: Any, depth: int = 0) -> str | None:
    if depth > 6 or not isinstance(value, dict):
        return None
    for key in ("created_at", "timestamp", "started_at"):
        found = _as_iso(value.get(key))
        if found:
            return found
    for key in ("blocks", "content"):
        if isinstance(value.get(key), list):
            for item in value[key]:
                found = _block_time(item, depth + 1)
                if found:
                    return found
    return None


def _message_time(message: dict[str, Any]) -> str | None:
    for key in ("created_at", "timestamp", "started_at"):
        found = _as_iso(message.get(key))
        if found:
            return found
    return _block_time(message.get("content"))


def _put(target: dict[str, Any], key: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return
        target[key] = stripped
        return
    if isinstance(value, (dict, list)) and len(value) == 0:
        return
    target[key] = value


def _keep(step: dict[str, Any]) -> bool:
    return any(key in step for key in _CONTENT_FIELDS) or "step_status" in step


def _string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _as_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return _string(value)


def _rejected(disposition: str, detail: str) -> dict[str, Any]:
    return {"disposition": disposition, "detail": detail, "episode": None}
