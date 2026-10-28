"""Bucket matching, tools, and threshold tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import make_episode, seed_bucket, service  # noqa: E402
from schema_validate import load_schema, validate_instance  # noqa: E402


class BucketAssignmentTest(unittest.TestCase):
    def test_exact_task_and_actions_join_one_bucket(self):
        created = service(threshold=3)
        first = created.ingest(make_episode("ep-1"))
        second = created.ingest(make_episode("ep-2", task="Debug API Timeout"))
        self.assertEqual(first["decision"], "create_new")
        self.assertEqual(second["decision"], "assign_existing")
        self.assertEqual(first["bucket"]["bucket_id"], second["bucket"]["bucket_id"])
        self.assertEqual(second["bucket"]["distinct_trace_count"], 2)
        self.assertEqual(second["bucket"]["representative_actions"], ["inspect_logs"])
        self.assertEqual(second["bucket"]["task_intent"], "debug api timeout")
        self.assertEqual(second["bucket"]["status"], "collecting")
        self.assertIsNone(second["skill"])

    def test_normalized_intent_matches_without_rewriting_the_seed(self):
        created = service()
        created.ingest(make_episode("ep-1", task="debug_api_timeout"))
        result = created.ingest(make_episode("ep-2", task="debug api timeout"))
        self.assertEqual(result["decision"], "assign_existing")
        self.assertEqual(result["bucket"]["task_intent"], "debug_api_timeout")

    def test_task_borderline_uses_the_configured_cutoff(self):
        created = service()
        created.ingest(make_episode("ep-1", task="alpha beta gamma delta epsilon", actions=["inspect"]))
        at_cutoff = created.buckets.search_buckets(
            make_episode("ep-2", task="alpha beta gamma", actions=["inspect"])
        )
        below = created.buckets.search_buckets(
            make_episode("ep-3", task="alpha beta", actions=["inspect"])
        )
        self.assertEqual(at_cutoff["task_threshold"], 0.6)
        self.assertEqual(at_cutoff["decision"], "assign_existing")
        self.assertEqual(below["decision"], "create_new")
        self.assertIn("task_below_threshold", below["candidates"][0]["reasons"])

    def test_reversed_actions_do_not_match_at_the_default_cutoff(self):
        created = service()
        created.ingest(make_episode("ep-1", actions=["inspect_logs", "restart_service"]))
        reversed_actions = created.ingest(
            make_episode("ep-2", actions=["restart_service", "inspect_logs"])
        )
        self.assertEqual(reversed_actions["decision"], "create_new")
        self.assertEqual(len(created.store.list_buckets()), 2)
        looser = service(action_threshold=0.5)
        looser.ingest(make_episode("ep-1", actions=["inspect_logs", "restart_service"]))
        joined = looser.ingest(make_episode("ep-2", actions=["restart_service", "inspect_logs"]))
        self.assertEqual(joined["decision"], "assign_existing")

    def test_extra_action_can_match_without_changing_the_representative_list(self):
        created = service()
        created.ingest(make_episode("ep-1", actions=["inspect_logs", "restart_service"]))
        result = created.ingest(
            make_episode("ep-2", actions=["inspect_logs", "restart_service", "check_health"])
        )
        self.assertEqual(result["decision"], "assign_existing")
        self.assertEqual(
            result["bucket"]["representative_actions"],
            ["inspect_logs", "restart_service"],
        )

    def test_tool_sets_must_be_equal_and_order_does_not_matter(self):
        created = service()
        created.ingest(make_episode("ep-1", tools=["logs", "metrics"]))
        reordered = created.ingest(make_episode("ep-2", tools=["metrics", "logs"]))
        different = created.ingest(make_episode("ep-3", tools=["logs"]))
        self.assertEqual(reordered["decision"], "assign_existing")
        self.assertEqual(different["decision"], "create_new")
        self.assertIn("available_tools_differ", different["candidates"][0]["reasons"])

    def test_unknown_permissions_are_not_treated_as_a_known_list(self):
        created = service()
        created.ingest(
            make_episode("ep-1", permissions=["read"], constraints=["maintenance-window"])
        )
        same = created.buckets.search_buckets(
            make_episode("ep-2", permissions=["read"], constraints=["maintenance-window"])
        )
        unknown = created.buckets.search_buckets(make_episode("ep-3"))
        self.assertEqual(same["decision"], "assign_existing")
        self.assertEqual(same["candidates"][0]["environment_certainty"], "full")
        self.assertEqual(unknown["decision"], "create_new")
        self.assertIn("permissions_unknown_mismatch", unknown["candidates"][0]["reasons"])

    def test_null_permissions_match_with_partial_certainty(self):
        created = service()
        created.ingest(make_episode("ep-1"))
        found = created.buckets.search_buckets(make_episode("ep-2"))
        self.assertEqual(found["decision"], "assign_existing")
        self.assertEqual(found["candidates"][0]["environment_certainty"], "partial")

    def test_missing_intent_or_actions_do_not_merge(self):
        created = service()
        created.ingest(make_episode("ep-1", task=None))
        second_unknown = created.ingest(make_episode("ep-2", task=None))
        created.ingest(make_episode("ep-3", actions=[]))
        fourth = created.ingest(make_episode("ep-4", actions=[]))
        self.assertEqual(second_unknown["decision"], "create_new")
        self.assertEqual(fourth["decision"], "create_new")
        self.assertEqual(len(created.store.list_buckets()), 4)

    def test_higher_task_score_wins_and_equal_scores_stay_ambiguous(self):
        created = service()
        seed_bucket(
            created.store,
            "bkt_0001",
            make_episode("seed-low", task="alpha beta gamma delta epsilon", actions=["inspect"]),
        )
        seed_bucket(
            created.store,
            "bkt_0002",
            make_episode("seed-high", task="alpha beta gamma", actions=["inspect"]),
        )
        winner = created.ingest(make_episode("ep-new", task="alpha beta gamma", actions=["inspect"]))
        self.assertEqual(winner["decision"], "assign_existing")
        self.assertEqual(winner["bucket"]["bucket_id"], "bkt_0002")

        tied = service()
        seed_bucket(tied.store, "bkt_0001", make_episode("seed-a", actions=["inspect"]))
        seed_bucket(tied.store, "bkt_0002", make_episode("seed-b", actions=["inspect"]))
        before = [bucket["bucket_id"] for bucket in tied.store.list_buckets()]
        result = tied.ingest(make_episode("ep-tie", actions=["inspect"]))
        self.assertEqual(result["decision"], "ambiguous")
        self.assertFalse(result["bucket_written"])
        self.assertIsNone(result["bucket"])
        self.assertEqual([bucket["bucket_id"] for bucket in tied.store.list_buckets()], before)
        self.assertIsNone(tied.store.get_episode("ep-tie")["bucket_id"])

    def test_higher_action_score_breaks_a_task_tie(self):
        created = service()
        seed_bucket(
            created.store,
            "bkt_0001",
            make_episode("seed-short", actions=["inspect_logs", "restart_service"]),
        )
        seed_bucket(
            created.store,
            "bkt_0002",
            make_episode("seed-full", actions=["inspect_logs", "restart_service", "check_health"]),
        )
        result = created.ingest(
            make_episode("ep-new", actions=["inspect_logs", "restart_service", "check_health"])
        )
        self.assertEqual(result["bucket"]["bucket_id"], "bkt_0002")

    def test_duplicate_episode_is_not_counted_twice(self):
        created = service(threshold=2)
        created.ingest(make_episode("ep-1"))
        again = created.ingest(make_episode("ep-1"))
        self.assertEqual(again["decision"], "already_assigned")
        self.assertEqual(again["bucket"]["distinct_trace_count"], 1)
        self.assertFalse(again["bucket_written"])

    def test_threshold_uses_distinct_episodes_not_reward(self):
        created = service(threshold=2)
        rewarded = make_episode(
            "ep-1",
            steps=[
                {
                    "index": 0,
                    "action": "inspect_logs",
                    "step_reward": 1.0,
                    "reward_metadata": {
                        "method": "progress_delta",
                        "p_before": 0.0,
                        "p_after": 1.0,
                        "status": "computed",
                        "rationale": None,
                    },
                }
            ],
        )
        first = created.ingest(rewarded)
        self.assertEqual(first["bucket"]["status"], "collecting")
        self.assertFalse(first["threshold_reached"])
        second = created.ingest(make_episode("ep-2"))
        self.assertEqual(second["bucket"]["status"], "ready_for_generation")
        self.assertEqual(second["bucket"]["distinct_trace_count"], 2)

    def test_check_recomputes_a_tampered_count(self):
        created = service(threshold=3)
        created.ingest(make_episode("ep-1"))
        bucket = created.store.get_bucket("bkt_0001")
        bucket["distinct_trace_count"] = 99
        created.store.replace_bucket(bucket)
        checked = created.buckets.check_bucket_threshold("bkt_0001")
        self.assertEqual(checked["distinct_trace_count"], 1)
        self.assertFalse(checked["reached"])
        self.assertEqual(checked["status"], "collecting")

    def test_tools_reject_unknown_ids_and_a_second_create(self):
        created = service()
        created.ingest(make_episode("ep-1"))
        missing = created.buckets.add_episode_to_bucket("bkt_0001", "missing")
        self.assertEqual(missing["error"], "unknown_episode")
        unknown = created.buckets.get_bucket("bkt_9999")
        self.assertEqual(unknown["error"], "unknown_bucket")
        twin = make_episode("ep-2")
        created.store.put_episode(twin)
        refused = created.buckets.create_bucket(twin)
        self.assertEqual(refused["error"], "suitable_bucket_exists")
        self.assertEqual(len(created.store.list_buckets()), 1)

    def test_search_does_not_write(self):
        created = service()
        created.ingest(make_episode("ep-1"))
        before = created.store.list_buckets()
        created.buckets.search_buckets(make_episode("ep-2"))
        self.assertEqual(created.store.list_buckets(), before)

    def test_proposal_cannot_override_the_matcher_or_set_a_count(self):
        created = service()
        episode = make_episode("ep-1")
        rejected = created.ingest_proposal(
            episode,
            {
                "decision": "assign_existing",
                "candidate_bucket_id": "bkt_0001",
                "reason": "high confidence guess",
                "confidence": 1,
            },
        )
        self.assertEqual(rejected["error"], "proposal_rejected")
        self.assertFalse(rejected["bucket_written"])
        self.assertEqual(created.store.list_buckets(), [])
        extra = created.ingest_proposal(
            episode,
            {
                "decision": "create_new",
                "candidate_bucket_id": None,
                "reason": "create",
                "confidence": 1,
                "distinct_trace_count": 99,
            },
        )
        self.assertEqual(extra["error"], "invalid_decision")
        assigned = created.ingest(episode)
        self.assertEqual(assigned["decision"], "create_new")
        self.assertEqual(assigned["bucket"]["distinct_trace_count"], 1)

    def test_closed_bucket_does_not_receive_another_episode(self):
        created = service(threshold=2, generator=self._idle_generator())
        created.ingest(make_episode("ep-1"))
        created.ingest(make_episode("ep-2"))
        self.assertEqual(created.store.get_bucket("bkt_0001")["status"], "skill_created")
        third = created.ingest(make_episode("ep-3"))
        self.assertEqual(third["decision"], "create_new")
        self.assertEqual(third["bucket"]["bucket_id"], "bkt_0002")
        self.assertEqual(len(created.store.get_bucket("bkt_0001")["episode_refs"]), 2)
        self.assertEqual(created.generator.calls, 1)

    def test_invalid_episode_is_not_stored(self):
        created = service()
        episode = make_episode("ep-1")
        episode["schema_version"] = 1
        result = created.ingest(episode)
        self.assertEqual(result["error"], "invalid_episode")
        self.assertFalse(result["episode_stored"])
        self.assertIsNone(created.store.get_episode("ep-1"))

    def test_bucket_schema_requires_the_contract_fields(self):
        errors = validate_instance({"bucket_id": "bkt_0001"}, load_schema("bucket.schema.json"))
        self.assertTrue(errors)

    def _idle_generator(self):
        from fixtures import generator

        return generator()


if __name__ == "__main__":
    unittest.main()
