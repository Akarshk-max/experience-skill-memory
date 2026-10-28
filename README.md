# Write Path

This folder is a standalone Trace Normalization Skill for completed Autobots runs. It does not plug into the application, and it does not modify the Autobots tree.

The skill turns one retrieved run document into an ordered episode: steps, a source reference, and the terminal status that was stored. It does not estimate rewards, score steps, discover skills, or call a model provider.

## Layout

```
Write Path/
  README.md
  trace-normalization/
    SKILL.md
    normalize_trace.py
    schema/episode.schema.json
    reference/
      trace-formats.md
      ordering-and-fallbacks.md
      redaction.md
      validation.md
    examples/
    tests/test_normalize_trace.py
  skill-memory/
    README.md
    autobots-reference/
    reference/architecture-notes.md
    tests/
```

`skill-memory/` is a separate workspace for a future Skill Memory prototype. It currently holds reference copies and architecture notes. It does not implement Skill Memory, and it does not change `trace-normalization/`.

`SKILL.md` is the instruction file. `normalize_trace.py` is the standard-library contract those instructions describe. The reference notes cite the Autobots source. Each file in `examples/` named `*.input.json` has a matching `*.output.json` produced by that contract.

## Run the tests

From `trace-normalization`, with any Python 3.11 or newer:

```bash
python -B -m unittest discover -s tests -v
```

No packages are installed. The tests do not import Autobots and do not open a database.

## Out of scope

Reward estimation, step values, semantic gradients, PPO gates, skill discovery, skill promotion, storage of episodes, and hooks into action, graph, team, or tool execution.
