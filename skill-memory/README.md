# Skill Memory prototype

This directory assigns normalized Episode v2 records to evidence buckets and, once a configurable count of distinct episodes is reached, stores one candidate skill.

Trace normalization stays in `Write Path/trace-normalization/`. This package reads that contract. It does not modify it. `autobots-reference/` is still reference material and is not imported.

Nothing here connects to MongoDB, Weaviate, or a model provider. `FakeSkillGenerator` is a test double. The instructions under `instructions/` describe what a future model should do. Matching and validation stay in code.

## Layout

```text
skill-memory/
  models.py
  bucket_assignment.py
  bucket_tools.py
  skill_draft.py
  skill_generation.py
  skill_validation.py
  skill_tools.py
  schema_validate.py
  schemas/
  instructions/
  storage/
  reference/
  tests/
  autobots-reference/
```

## Behavior

1. Validate an Episode v2 document.
2. Search open buckets with the deterministic matcher in `reference/bucket-matching.md`.
3. Assign the episode, create a bucket, or return `ambiguous` without writing.
4. Store episode references, not copies of the trace, on the bucket.
5. When the distinct-episode count reaches the threshold, call `SkillGenerator.generate`.
6. Validate the draft, store a `candidate` skill, and set the bucket to `skill_created`.

The default threshold is 3 episodes. The default task and action cutoffs are 0.6. Both are constructor arguments on `SkillCreationService`. Reward values are not the threshold.

A failed draft sets `generation_failed`, leaves the references in place, and can be retried. A second successful generation reuses the stored skill.

## Storage

`storage/memory_store.py` is the in-memory store used by the tests. `storage/mongo_store.py` talks only to injected collection objects named `SkillMemoryBuckets`, `SkillMemorySkills`, and `SkillMemoryEpisodes`. `storage/weaviate_index.py` stays disabled until an embedder is injected. Details are in `reference/storage.md`.

## Not in this prototype

Existing-skill search, skill revision, promotion, PPO, live database clients, and a live language model.

## Tests

From `Write Path/skill-memory`:

```bash
python -B -m unittest discover -s tests -v
```

Normalization regression stays in `Write Path/trace-normalization` and is run separately.
