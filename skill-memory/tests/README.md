# Tests

From `Write Path/skill-memory`:

```bash
python -B -m unittest discover -s tests -v
```

The tests use the in-memory store, `InMemoryMongoCollection`, and a fake vector client. They do not open MongoDB, Weaviate, or a model provider. `FakeSkillGenerator` returns predetermined drafts.

`test_skill_generation.py` also reads `Write Path/trace-normalization/examples/tool_run.output.json`. It does not modify that package.
