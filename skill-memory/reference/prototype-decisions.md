# Prototype decisions

The inspection notes in `architecture-notes.md` stay a reading of the AutoBots checkout. This file records the choices made for the standalone prototype.

- Episode v2 is the input. `bucket_id` stays null until this package assigns it on the stored copy. Trace normalization is not modified.
- Bucket matching is deterministic. See `bucket-matching.md`. Embeddings are not used for assignment.
- A bucket stores episode references. The episode collection stores the normalized episode. Skills store the same references plus a candidate procedure.
- The distinct-trace threshold defaults to 3. It is a count of episode ids, not a reward sum.
- Skill status is `candidate` and `version` is 1. Nothing is published.
- `reward_summary.aggregation` stays `not_defined`. Computed progress-delta steps are listed. Pending and rejected steps are not turned into numbers.
- MongoDB and Weaviate are behind adapters. See `storage.md`. Neither is contacted.
- `FakeSkillGenerator` is a test double. `instructions/skill_generation.md` is the text a future model would follow. No model provider is connected.
- Existing-skill search, skill revision, PPO gates, and promotion are not implemented.
