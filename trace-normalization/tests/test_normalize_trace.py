"""Standard-library checks for the trace-normalization contract.

Run from the trace-normalization directory:

    python -B -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import normalize_trace  # noqa: E402

EXAMPLES = ROOT / "examples"
SCHEMA = json.loads((ROOT / "schema" / "episode.schema.json").read_text(encoding="utf-8"))

FORBIDDEN_EPISODE_FIELDS = {
    "reward",
    "score",
    "step_value",
    "advantage",
    "return",
    "config",
    "shared_with",
    "user_manual",
}
SENTINELS = (
    "fixture-token",
    "fixture-secret",
    "fixture-inline",
    "fixture-bearer-value",
    "fixture-answer-secret",
    "fixture-query",
    "config-sentinel",
    "MANUAL-SENTINEL",
    "space-sentinel",
    "ROW-SENTINEL",
    "INNER-SENTINEL",
    "OUTPUT-ONLY-SENTINEL",
    "THREAD-WINS-SENTINEL",
    "OPTION-SENTINEL",
    "answer-url-sentinel",
    "opaque-reasoning-fixture",
    "12.5",
    "77",
)


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def normalize_example(name: str) -> dict:
    return normalize_trace.normalize_trace(load_example(name))


def _matches_type(value, types: list[str]) -> bool:
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    return any(checks[kind](value) for kind in types)


def assert_schema(instance, schema, path="$"):
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        assert_schema(instance, SCHEMA["$defs"][name], path)
        return
    if "const" in schema:
        if instance != schema["const"]:
            raise AssertionError(f"{path} expected {schema['const']!r}, got {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        raise AssertionError(f"{path} value {instance!r} is not in {schema['enum']}")
    types = schema.get("type")
    if isinstance(types, str):
        types = [types]
    if types and not _matches_type(instance, types):
        raise AssertionError(f"{path} has type {type(instance).__name__}, schema wants {types}")
    if isinstance(instance, dict) and schema.get("properties") is not None:
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(instance) - set(properties)
            if extra:
                raise AssertionError(f"{path} has unexpected fields {sorted(extra)}")
        for key in schema.get("required", []):
            if key not in instance:
                raise AssertionError(f"{path} is missing {key}")
        for key, value in instance.items():
            if key in properties:
                assert_schema(value, properties[key], f"{path}.{key}")
    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            assert_schema(item, schema["items"], f"{path}[{index}]")
    if "minimum" in schema and isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if instance < schema["minimum"]:
            raise AssertionError(f"{path} is below {schema['minimum']}")
    if "maximum" in schema and isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if instance > schema["maximum"]:
            raise AssertionError(f"{path} is above {schema['maximum']}")


def assert_episode_contract(episode: dict) -> None:
    assert_schema(episode, SCHEMA)
    allowed = (
        ("success", "error", "cancelled", "stuck")
        if episode["event_type"] == "tool_run"
        else ("success", "error", "cancelled")
    )
    if episode["outcome"] not in allowed:
        raise AssertionError(episode["outcome"])
    if episode["episode_id"] != episode["source_run_id"]:
        raise AssertionError("episode id drifted from the source run id")
    if episode["source"]["source_run_id"] != episode["episode_id"]:
        raise AssertionError("source run id drifted")
    indexes = [step["index"] for step in episode["steps"]]
    if indexes != list(range(len(episode["steps"]))):
        raise AssertionError(indexes)
    if episode["schema_version"] != 2:
        raise AssertionError(episode["schema_version"])
    if episode["bucket_id"] is not None:
        raise AssertionError("bucket_id was assigned during normalization")
    if episode["reward_metadata"] != {
        "method": "progress_delta",
        "status": "pending",
        "aggregation": "not_defined",
    }:
        raise AssertionError(episode["reward_metadata"])
    if episode["environment"]["permissions"] is not None:
        raise AssertionError("permissions were invented")
    if episode["environment"]["constraints"] is not None:
        raise AssertionError("constraints were invented")
    actions = [step["action"] for step in episode["steps"] if "action" in step]
    if episode["actions"] != actions:
        raise AssertionError(episode["actions"])
    for step in episode["steps"]:
        if step["step_reward"] is not None:
            raise AssertionError("normalize_trace invented a step reward")
        meta = step["reward_metadata"]
        if (
            meta["status"] != "pending"
            or meta["p_before"] is not None
            or meta["p_after"] is not None
            or meta["rationale"] is not None
        ):
            raise AssertionError(meta)
    blob = json.dumps(episode)
    for field in FORBIDDEN_EPISODE_FIELDS:
        if f'"{field}"' in blob:
            raise AssertionError(f"episode copied {field}")
    for sentinel in SENTINELS:
        if sentinel in blob:
            raise AssertionError(f"episode kept {sentinel}")


class NormalizeTraceTest(unittest.TestCase):
    def test_action_archive_orders_turns_and_redacts(self):
        result = normalize_example("action_archive.input.json")
        self.assertEqual(result["disposition"], "normalized")
        episode = result["episode"]
        assert_episode_contract(episode)
        self.assertEqual(episode["episode_id"], "run-archive-1")
        self.assertEqual(
            episode["task_summary"],
            "Lookup account\nFind whether the account is active.",
        )
        self.assertEqual(episode["task_intent"], "Find whether the account is active.")
        self.assertEqual(episode["actions"], ["Look up account 42", "lookup_account"])
        self.assertEqual(episode["environment"]["available_tools"], ["lookup_account"])
        self.assertIsNone(episode["bucket_id"])
        self.assertEqual(
            episode["source"]["file_url"],
            "https://files.example/action_runs/user-1/run-archive-1.json",
        )
        steps = episode["steps"]
        self.assertEqual(
            [step["action"] for step in steps[:2]],
            ["Look up account 42", "lookup_account"],
        )
        self.assertEqual(steps[0]["turn_no"], 1)
        self.assertEqual(steps[0]["timestamp"], "2026-10-28T00:00:01Z")
        self.assertEqual(steps[1]["call_id"], "call-1")
        self.assertEqual(steps[1]["tool_arguments"], {"account_id": "42"})
        self.assertEqual(steps[1]["tool_result"], "status=active api_key: ***REDACTED***")
        self.assertEqual(steps[2]["observation"], "Account 42 is active.")
        self.assertNotIn("started_at", steps[1])
        self.assertTrue(any("input_archive supplied the steps" in note for note in episode["warnings"]))
        self.assertTrue(any("query string" in note for note in episode["warnings"]))
        self.assertTrue(any("queued_inputs" in note for note in episode["warnings"]))

    def test_action_results_keep_order_timing_and_error(self):
        episode = normalize_example("action_results.input.json")["episode"]
        assert_episode_contract(episode)
        self.assertEqual(episode["outcome"], "error")
        self.assertEqual(episode["error_message"], "provider timed out")
        first, second = episode["steps"]
        self.assertEqual(first["action"], "first")
        self.assertEqual(first["observation"], "second")
        self.assertEqual(first["timestamp"], "2026-10-28T01:00:01Z")
        self.assertEqual(first["started_at"], "2026-10-28T01:00:01Z")
        self.assertEqual(first["ended_at"], "2026-10-28T01:00:02Z")
        self.assertEqual(first["duration_ms"], 1000)
        self.assertEqual(first["attempt"], 1)
        self.assertEqual(first["turn_no"], 0)
        self.assertEqual(first["step_status"], "success")
        self.assertEqual(second["action"], "retry")
        self.assertEqual(second["error"], "token: ***REDACTED***")
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(second["turn_no"], 1)
        self.assertEqual(second["step_status"], "error")
        self.assertNotIn("observation", second)
        self.assertIsNone(second["step_reward"])
        self.assertEqual(second["reward_metadata"]["status"], "pending")
        self.assertEqual(episode["task_intent"], "Plain action")
        self.assertEqual(episode["actions"], ["first", "retry"])
        self.assertEqual(episode["environment"]["available_tools"], [])

    def test_graph_vectors_follow_node_order_and_context_sort(self):
        episode = normalize_example("graph_vectors.input.json")["episode"]
        assert_episode_contract(episode)
        self.assertEqual(episode["episode_id"], "run-graph-1")
        steps = episode["steps"]
        self.assertEqual(
            [(step["node_id"], step["provenance_node_id"], step["action"]) for step in steps],
            [
                ("n2", "start", "n2 start"),
                ("n1", "start", "from start"),
                ("n1", "redirect", "from redirect"),
            ],
        )
        self.assertEqual(steps[0]["observation"], "n2 out")
        self.assertNotIn("action_name", steps[0])
        self.assertEqual(steps[1]["observation"], "start out")
        self.assertEqual(steps[1]["action_name"], "First node")
        self.assertEqual(steps[2]["action_name"], "First node")
        notes = "\n".join(episode["warnings"])
        self.assertIn("not in output", notes)
        self.assertIn("Dropped a repeated context entry on node n1", notes)
        self.assertIn("were not expanded", notes)
        self.assertIn("only_output", notes)
        self.assertNotIn("later slot", json.dumps(episode))

    def test_plain_graph_follows_output_key_order(self):
        episode = normalize_example("graph_output.input.json")["episode"]
        assert_episode_contract(episode)
        self.assertEqual(
            [(step["node_id"], step["action"], step["action_name"]) for step in episode["steps"]],
            [("b", "bee in", "Bee"), ("a", "ay in", "Ay")],
        )
        self.assertEqual(episode["warnings"], [])

    def test_team_thread_keeps_role_and_child_run(self):
        episode = normalize_example("team_thread.input.json")["episode"]
        assert_episode_contract(episode)
        first, second = episode["steps"]
        self.assertEqual(first["role"], "member")
        self.assertEqual(first["action_name"], "Researcher")
        self.assertEqual(first["action_run_id"], "child-run-1")
        self.assertEqual(first["member_id"], "member-1")
        self.assertEqual(first["duration_ms"], 5000)
        self.assertEqual(first["timestamp"], "2026-10-28T02:00:00Z")
        self.assertEqual(second["role"], "leader")
        self.assertEqual(second["action"], "approve it")
        self.assertNotIn("action_id", second)
        self.assertTrue(any("current_active_members" in note for note in episode["warnings"]))

    def test_tool_run_is_one_step(self):
        episode = normalize_example("tool_run.input.json")["episode"]
        assert_episode_contract(episode)
        self.assertEqual(len(episode["steps"]), 1)
        step = episode["steps"][0]
        self.assertEqual(step["action"], "lookup_account")
        self.assertEqual(step["tool_arguments"], {"account_id": "42"})
        self.assertEqual(step["tool_result"], "bearer: ***REDACTED***")
        self.assertEqual(step["timestamp"], "2026-10-28T03:00:00Z")
        self.assertEqual(episode["task_summary"], "lookup_account")
        self.assertEqual(episode["task_intent"], "lookup_account")
        self.assertEqual(episode["environment"]["available_tools"], ["lookup_account"])

    def test_file_url_without_body_is_not_loaded(self):
        result = normalize_example("action_lite_file_url.input.json")
        self.assertEqual(result["disposition"], "payload_not_loaded")
        self.assertIsNone(result["episode"])
        self.assertIn("not treated as loaded", result["detail"])

    def test_nonterminal_status_is_incomplete(self):
        result = normalize_example("action_processing.input.json")
        self.assertEqual(result["disposition"], "incomplete")
        self.assertIsNone(result["episode"])
        self.assertIn("processing", result["detail"])
        self.assertIn("not on this document", result["detail"])

    def test_blank_status_does_not_invent_success(self):
        result = normalize_example("action_blank_status.input.json")
        self.assertEqual(result["disposition"], "outcome_unavailable")
        self.assertIsNone(result["episode"])

    def test_datastore_put_is_not_an_execution_trace(self):
        result = normalize_example("datastore_put.input.json")
        self.assertEqual(result["disposition"], "unreadable")
        self.assertIsNone(result["episode"])
        self.assertIn("datastore_put", result["detail"])

    def test_stuck_follows_the_two_terminal_sets(self):
        tool = normalize_example("tool_stuck.input.json")
        self.assertEqual(tool["disposition"], "normalized")
        self.assertEqual(tool["episode"]["outcome"], "stuck")
        self.assertEqual(tool["episode"]["steps"][0]["action"], "wait_for_user")
        self.assertNotIn("tool_arguments", tool["episode"]["steps"][0])
        self.assertNotIn("tool_result", tool["episode"]["steps"][0])
        action = normalize_example("action_stuck.input.json")
        self.assertEqual(action["disposition"], "incomplete")
        self.assertIsNone(action["episode"])

    def test_error_without_a_message_does_not_invent_one(self):
        episode = normalize_example("action_error_without_message.input.json")["episode"]
        assert_episode_contract(episode)
        self.assertEqual(episode["outcome"], "error")
        self.assertNotIn("error_message", episode)
        self.assertEqual(episode["steps"][0]["observation"], "failed visibly")

    def test_human_question_stays_beside_the_steps(self):
        episode = normalize_example("action_human_question.input.json")["episode"]
        assert_episode_contract(episode)
        self.assertEqual(episode["source"]["parent_action_result_id"], "parent-1")
        self.assertEqual(episode["source"]["run_kind"], "subagent")
        self.assertEqual(len(episode["steps"]), 1)
        self.assertNotIn("question", episode["steps"][0])
        question = episode["human_questions"][0]
        self.assertEqual(question["question_id"], "q-1")
        self.assertEqual(question["turn_index"], 0)
        self.assertEqual(question["question"], "Which account?")
        self.assertEqual(question["answer_text"], "api_key: ***REDACTED***")
        self.assertEqual(question["answer_selected"], ["42"])
        self.assertIs(question["answer_skipped"], False)
        self.assertNotIn("answered_by", question)
        self.assertNotIn("user-9", json.dumps(episode))

    def test_same_document_normalizes_twice_to_the_same_episode(self):
        document = load_example("action_archive.input.json")
        self.assertEqual(
            normalize_trace.normalize_trace(document),
            normalize_trace.normalize_trace(document),
        )

    def test_missing_document_and_empty_body_and_urls(self):
        missing = normalize_trace.normalize_trace(None)
        self.assertEqual(missing["disposition"], "unreadable")
        self.assertIsNone(missing["episode"])

        cancelled = normalize_trace.normalize_trace(
            {
                "_id": "run-empty",
                "type": "action_run",
                "status": "cancelled",
                "result": {"results": []},
            }
        )
        self.assertEqual(cancelled["disposition"], "normalized")
        self.assertEqual(cancelled["episode"]["outcome"], "cancelled")
        self.assertEqual(cancelled["episode"]["steps"], [])
        self.assertIsNone(cancelled["episode"]["task_intent"])
        self.assertEqual(cancelled["episode"]["actions"], [])

        urls = normalize_trace.normalize_trace(
            {
                "_id": "run-urls",
                "type": "action_run",
                "status": "success",
                "result": {"input": {"urls": ["https://files.example/only-url"]}, "output": None},
            }
        )
        self.assertEqual(urls["disposition"], "normalized")
        self.assertEqual(urls["episode"]["steps"], [])
        self.assertIn(normalize_trace._URLS_WARNING, urls["episode"]["warnings"])
        self.assertNotIn("only-url", json.dumps(urls["episode"]))

        unknown = normalize_trace.normalize_trace(
            {
                "_id": "run-unknown-message",
                "type": "action_run",
                "status": "success",
                "result": {
                    "config": {
                        "input_archive": [
                            {
                                "turn_number": 0,
                                "input": [{"type": "note", "text": "untyped note"}],
                            }
                        ]
                    }
                },
            }
        )
        self.assertEqual(unknown["episode"]["steps"][0]["observation"], "untyped note")
        self.assertIn(normalize_trace._UNKNOWN_MESSAGE_WARNING, unknown["episode"]["warnings"])

    def test_checked_in_outputs_match_the_normalizer(self):
        for path in sorted(EXAMPLES.glob("*.input.json")):
            expected_path = path.with_name(path.name.replace(".input.json", ".output.json"))
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            actual = normalize_trace.normalize_trace(json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(actual, expected, path.name)

    def test_every_example_rejects_or_matches_the_schema(self):
        for path in sorted(EXAMPLES.glob("*.input.json")):
            result = normalize_trace.normalize_trace(
                json.loads(path.read_text(encoding="utf-8"))
            )
            self.assertIn(
                result["disposition"],
                {
                    "normalized",
                    "payload_not_loaded",
                    "incomplete",
                    "outcome_unavailable",
                    "unreadable",
                },
            )
            if result["disposition"] == "normalized":
                assert_episode_contract(result["episode"])
            else:
                self.assertIsNone(result["episode"])

    def test_ambiguous_status_is_not_called_success(self):
        result = normalize_trace.normalize_trace(
            {
                "_id": "run-ambiguous",
                "type": "action_run",
                "status": "mystery",
                "result": {"input": {"text": "did something"}, "output": {"text": "unclear"}},
            }
        )
        self.assertEqual(result["disposition"], "incomplete")
        self.assertIsNone(result["episode"])

    def test_progress_delta_arithmetic_and_rejections(self):
        episode = normalize_example("tool_run.input.json")["episode"]
        original = json.loads(json.dumps(episode))

        computed = normalize_trace.apply_progress_grades(
            episode,
            [{"index": 0, "p_before": 0.25, "p_after": 0.75, "rationale": "Tool result was present."}],
        )
        step = computed["steps"][0]
        self.assertEqual(step["step_reward"], 0.5)
        self.assertEqual(step["reward_metadata"]["status"], "computed")
        self.assertEqual(step["reward_metadata"]["p_before"], 0.25)
        self.assertEqual(step["reward_metadata"]["p_after"], 0.75)
        self.assertEqual(step["reward_metadata"]["rationale"], "Tool result was present.")
        self.assertEqual(computed["reward_metadata"]["aggregation"], "not_defined")
        self.assertEqual(computed["reward_metadata"]["status"], "pending")
        self.assertEqual(computed["outcome"], "success")
        self.assertIsNone(computed["bucket_id"])
        assert_schema(computed, SCHEMA)
        self.assertEqual(episode, original)

        bounds = normalize_trace.apply_progress_grades(
            episode,
            [{"index": 0, "p_before": 0, "p_after": 1}],
        )
        self.assertEqual(bounds["steps"][0]["step_reward"], 1.0)
        self.assertIsNone(bounds["steps"][0]["reward_metadata"]["rationale"])

        decrease = normalize_trace.apply_progress_grades(
            episode,
            [
                {
                    "index": 0,
                    "p_before": 0.5,
                    "p_after": 0.25,
                    "rationale": "token: fixture-token",
                }
            ],
        )
        self.assertEqual(decrease["steps"][0]["step_reward"], -0.25)
        self.assertEqual(
            decrease["steps"][0]["reward_metadata"]["rationale"],
            "token: ***REDACTED***",
        )
        self.assertNotIn("fixture-token", json.dumps(decrease))

        missing = normalize_trace.apply_progress_grades(
            episode,
            [{"index": 0, "p_before": 0.25, "p_after": None, "rationale": "unused"}],
        )
        self.assertIsNone(missing["steps"][0]["step_reward"])
        self.assertEqual(missing["steps"][0]["reward_metadata"]["status"], "pending")
        self.assertIsNone(missing["steps"][0]["reward_metadata"]["p_before"])
        self.assertIsNone(missing["steps"][0]["reward_metadata"]["rationale"])

        rejected_cases = [
            {"index": 0, "p_before": 1.5, "p_after": 0.2, "rationale": "do not keep"},
            {"index": 0, "p_before": True, "p_after": 0.5, "rationale": "do not keep"},
            {"index": 0, "p_before": "0.2", "p_after": 0.4},
            {"index": 0, "p_before": float("nan"), "p_after": 0.4},
            {"index": 0, "p_before": float("inf"), "p_after": 0.4},
            {"index": 0, "p_before": -0.01, "p_after": 0.4},
        ]
        for grade in rejected_cases:
            rejected = normalize_trace.apply_progress_grades(episode, [grade])
            meta = rejected["steps"][0]["reward_metadata"]
            self.assertEqual(meta["status"], "rejected", grade)
            self.assertIsNone(rejected["steps"][0]["step_reward"])
            self.assertIsNone(meta["p_before"])
            self.assertIsNone(meta["p_after"])
            self.assertIsNone(meta["rationale"])

        untouched = normalize_trace.apply_progress_grades(episode, {"p_before": 0.1, "p_after": 0.9})
        self.assertEqual(untouched["steps"][0]["reward_metadata"]["status"], "pending")
        self.assertIsNone(untouched["steps"][0]["step_reward"])

        skipped = normalize_trace.apply_progress_grades(
            episode,
            [{"index": 4, "p_before": 0.1, "p_after": 0.2}],
        )
        self.assertEqual(skipped["steps"][0]["reward_metadata"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
