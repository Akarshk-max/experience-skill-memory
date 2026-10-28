"""Skill generation, reward evidence, and failure retry tests."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import computed_step, generator, make_episode, service  # noqa: E402
from schema_validate import load_schema, validate_instance  # noqa: E402


TRACE_EPISODE = (
    Path(__file__).resolve().parents[2]
    / "trace-normalization"
    / "examples"
    / "tool_run.output.json"
)


class SkillGenerationTest(unittest.TestCase):
    def test_threshold_creates_one_candidate_skill_from_real_episode_output(self):
        payload = json.loads(TRACE_EPISODE.read_text(encoding="utf-8"))
        first = payload["episode"]
        second = copy.deepcopy(first)
        second["episode_id"] = "run-tool-2"
        second["source_run_id"] = "run-tool-2"
        second["source"]["source_run_id"] = "run-tool-2"
        created = service(threshold=2, generator=generator())
        created.ingest(first)
        result = created.ingest(second)
        self.assertTrue(result["skill_created"])
        skill = result["skill"]
        self.assertEqual(skill["status"], "candidate")
        self.assertEqual(skill["version"], 1)
        self.assertEqual(skill["schema_version"], 1)
        self.assertEqual(
            [ref["episode_id"] for ref in skill["evidence_refs"]],
            ["run-tool-1", "run-tool-2"],
        )
        self.assertEqual(skill["environment_conditions"]["required_tools"], ["lookup_account"])
        self.assertIsNone(skill["environment_conditions"]["permissions"])
        self.assertEqual(skill["reward_summary"]["aggregation"], "not_defined")
        self.assertEqual(skill["reward_summary"]["computed_steps"], [])
        self.assertEqual(skill["reward_summary"]["episodes_without_computed_reward"], 2)
        self.assertEqual(validate_instance(skill, load_schema("skill.schema.json")), [])
        self.assertNotIn("total_reward", json.dumps(skill))
        self.assertEqual(created.generator.calls, 1)
        again = created.ingest(second)
        self.assertEqual(again["decision"], "already_assigned")
        self.assertEqual(created.generator.calls, 1)

    def test_reward_summary_lists_estimates_and_does_not_sum_them(self):
        created = service(threshold=2, generator=generator())
        created.ingest(
            make_episode(
                "ep-ok",
                outcome="success",
                steps=[
                    computed_step(0, "inspect_logs", 0.25, 0.75, observation="timeout_detected")
                ],
            )
        )
        result = created.ingest(
            make_episode(
                "ep-down",
                outcome="success",
                steps=[computed_step(0, "inspect_logs", 0.5, 0.25, observation="timeout_detected")],
            )
        )
        summary = result["skill"]["reward_summary"]
        self.assertEqual(
            summary["computed_steps"],
            [
                {
                    "episode_id": "ep-ok",
                    "step_index": 0,
                    "step_reward": 0.5,
                    "method": "progress_delta",
                },
                {
                    "episode_id": "ep-down",
                    "step_index": 0,
                    "step_reward": -0.25,
                    "method": "progress_delta",
                },
            ],
        )
        self.assertEqual(summary["aggregation"], "not_defined")
        self.assertEqual(summary["episodes_without_computed_reward"], 0)
        self.assertEqual(result["skill"]["procedure"][0]["expected_observation"], "timeout_detected")
        self.assertTrue(
            any("negative" in line for line in result["skill"]["failure_handling"])
        )

    def test_disagreeing_observations_are_not_copied(self):
        created = service(threshold=2, generator=generator())
        created.ingest(
            make_episode("ep-1", steps=[computed_step(0, "inspect_logs", 0.0, 0.0, observation="one")])
        )
        result = created.ingest(
            make_episode("ep-2", steps=[computed_step(0, "inspect_logs", 0.0, 0.0, observation="two")])
        )
        self.assertIsNone(result["skill"]["procedure"][0]["expected_observation"])

    def test_pending_and_rejected_rewards_stay_out_of_the_summary(self):
        created = service(threshold=1, generator=generator())
        episode = make_episode(
            "ep-1",
            steps=[
                {
                    "index": 0,
                    "action": "inspect_logs",
                    "step_reward": None,
                    "reward_metadata": {
                        "method": "progress_delta",
                        "p_before": None,
                        "p_after": None,
                        "status": "rejected",
                        "rationale": None,
                    },
                }
            ],
        )
        result = created.ingest(episode)
        self.assertEqual(result["skill"]["reward_summary"]["computed_steps"], [])
        self.assertEqual(result["skill"]["reward_summary"]["episodes_without_computed_reward"], 1)

    def test_failed_outcome_is_named_and_permissions_are_not_invented(self):
        created = service(threshold=1, generator=generator())
        result = created.ingest(make_episode("ep-1", outcome="error"))
        self.assertTrue(any("error" in line for line in result["skill"]["failure_handling"]))
        self.assertIsNone(result["skill"]["environment_conditions"]["permissions"])
        self.assertEqual(result["skill"]["environment_conditions"]["prerequisites"], [])
        self.assertEqual(result["skill"]["constraints"], [])

    def test_invalid_generator_output_does_not_create_a_skill_and_retry_is_safe(self):
        fake = generator("published")
        created = service(threshold=1, generator=fake)
        failed = created.ingest(make_episode("ep-1"))
        bucket_id = failed["bucket"]["bucket_id"]
        self.assertFalse(failed["generation"]["ok"])
        self.assertIsNone(failed["skill"])
        self.assertEqual(created.store.get_bucket(bucket_id)["status"], "generation_failed")
        self.assertEqual(len(created.store.get_bucket(bucket_id)["episode_refs"]), 1)
        self.assertIsNone(created.store.get_skill(f"skl_{bucket_id}"))
        refs = created.store.get_bucket(bucket_id)["episode_refs"]

        fake.mode = "valid"
        retried = created.generate_for_bucket(bucket_id)
        self.assertTrue(retried["ok"])
        self.assertEqual(created.store.get_bucket(bucket_id)["status"], "skill_created")
        self.assertEqual(created.store.get_bucket(bucket_id)["episode_refs"], refs)
        self.assertEqual(fake.calls, 2)
        second = created.generate_for_bucket(bucket_id)
        self.assertTrue(second["idempotent"])
        self.assertEqual(fake.calls, 2)

    def test_generator_exception_and_each_invalid_mode(self):
        for mode in ("raise", "not_a_dict", "unknown_tool", "bad_reward", "invented_permission", "unknown_evidence", "trajectory"):
            created = service(threshold=1, generator=generator(mode))
            result = created.ingest(make_episode("ep-1", task=f"task {mode}"))
            self.assertEqual(result["bucket"]["status"], "generation_failed", mode)
            self.assertIsNone(result["skill"], mode)
            self.assertEqual(created.store.skills, {}, mode)

    def test_omitted_reward_summary_is_filled_from_evidence(self):
        created = service(threshold=1, generator=generator("omit_reward"))
        result = created.ingest(make_episode("ep-1"))
        self.assertEqual(result["skill"]["reward_summary"]["aggregation"], "not_defined")
        self.assertEqual(result["skill"]["reward_summary"]["computed_steps"], [])

    def test_missing_evidence_fails_without_inventing_an_episode(self):
        created = service(threshold=1, generator=None)
        stored = created.ingest(make_episode("ep-1"))
        bucket_id = stored["bucket"]["bucket_id"]
        del created.store.episodes["ep-1"]
        created.generator = generator()
        failed = created.generate_for_bucket(bucket_id)
        self.assertEqual(failed["error"], "missing_evidence")
        self.assertEqual(created.store.get_bucket(bucket_id)["status"], "generation_failed")
        self.assertEqual(created.store.skills, {})
        created.store.put_episode(make_episode("ep-1"))
        restored = created.generate_for_bucket(bucket_id)
        self.assertTrue(restored["ok"])
        self.assertEqual(created.generator.calls, 1)

    def test_existing_skill_is_reused_without_calling_the_generator_again(self):
        fake = generator()
        created = service(threshold=1, generator=fake)
        result = created.ingest(make_episode("ep-1"))
        bucket = created.store.get_bucket(result["bucket"]["bucket_id"])
        bucket["status"] = "ready_for_generation"
        bucket["skill_id"] = None
        bucket["generation_error"] = None
        created.store.replace_bucket(bucket)
        reused = created.generate_for_bucket(bucket["bucket_id"])
        self.assertTrue(reused["idempotent"])
        self.assertEqual(fake.calls, 1)
        self.assertEqual(created.store.get_bucket(bucket["bucket_id"])["status"], "skill_created")

    def test_changed_episode_identity_is_rejected(self):
        created = service()
        created.ingest(make_episode("ep-1"))
        changed = make_episode("ep-1", task="other task")
        result = created.ingest(changed)
        self.assertEqual(result["error"], "episode_identity_conflict")
        self.assertEqual(created.store.get_episode("ep-1")["task_intent"], "debug api timeout")

    def test_published_status_fails_the_skill_schema(self):
        errors = validate_instance({"status": "published"}, load_schema("skill.schema.json"))
        self.assertTrue(any("candidate" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
