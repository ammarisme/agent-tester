# agent-tester (runner)

The finite evaluation runner behind Agent Tester. It loads agents and a dataset,
invokes every agent on every case (optionally several times), scores the
responses, and reports distributions. Then it exits.

```bash
pip install ./tester
agent-tester run --agent ../presets/mock-echo.json --param base_url=http://localhost:9999 --dataset ../datasets/samples/smoke.jsonl
```

See the [CLI guide](../docs/cli.md) for all flags, CI gating and JUnit output.
