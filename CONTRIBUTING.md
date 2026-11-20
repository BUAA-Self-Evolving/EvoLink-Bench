# Contributing

Use Python 3.11+ and an isolated environment. Run offline checks before requesting a review:

```bash
python -m pip install -e .
python -m pip install pytest jsonschema
python -m pytest tests -q
python -m compileall -q evolink_bench baseline/adapters tools
```

Keep changes scoped. Preserve schema fields, existing imports, saved-report compatibility, and public/private evidence boundaries. Runtime changes need meaningful regression coverage for the affected execution, grading, state, or recovery behavior. Use fake transports and adapters; do not call paid models in unit tests.

Do not change scores or datasets while cleaning documentation or packaging. Record package/image/source digests for any real evaluation. Preserve failed-attempt evidence and unknown usage. Never commit credentials, personal configuration, raw private tasks/answers, traces, or checkpoints.

When an optional test needs an external package or built binary, mark the requirement explicitly. Unit tests should construct their own temporary source fixtures instead of requiring a research server checkout.

Pull requests should explain the problem, resulting behavior, compatibility implications, and checks performed. Clearly distinguish a documentation-only change from a changed evaluation protocol.
