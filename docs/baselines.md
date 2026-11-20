# Baseline setup

The adapters are part of this source tree. Third-party agent repositories are not vendored. Obtain them separately at the revisions recorded in their manifests; an arbitrary latest checkout is not equivalent to an evaluated revision.

| Baseline ID | Expected source directory | Adapter build recipe |
| --- | --- | --- |
| `hermes` | `baseline/hermes-agent` | `baseline/adapters/hermes/Dockerfile` |
| `prime-agent` | `baseline/prime-agent` | `baseline/adapters/prime_agent/Dockerfile` |
| `adaptive-auto-harness` | `baseline/adaptive-auto-harness` | `baseline/adapters/adaptive_auto_harness/Dockerfile` |
| `opencode` | `baseline/opencode` | `baseline/adapters/opencode/Dockerfile` |
| `codex` | `baseline/codex` | `baseline/adapters/codex/Dockerfile` |

Upstream repository addresses and declared revisions are in [THIRD_PARTY.md](../THIRD_PARTY.md). For example:

```bash
git clone https://github.com/NousResearch/hermes-agent.git baseline/hermes-agent
git -C baseline/hermes-agent checkout 53873bfae5dfdd5f1af5cb6203a441f6e75330c1
docker build -t evolink-hermes:0.1 -f baseline/adapters/hermes/Dockerfile .
```

The manifest verifies the source revision and clean tree. Do not enable `allow_revision_mismatch` merely to silence a version error. A Docker build command may download sizeable language toolchains and dependencies; it is not part of the small offline smoke setup.

Other standard image builds, after obtaining their pinned source:

```bash
docker build -t evolink-prime-agent:0.1 -f baseline/adapters/prime_agent/Dockerfile .
docker build -t evolink-adaptive-auto-harness:0.1 -f baseline/adapters/adaptive_auto_harness/Dockerfile .
docker build -t evolink-opencode:0.1 -f baseline/adapters/opencode/Dockerfile .
docker build -t evolink-codex:0.1 -f baseline/adapters/codex/Dockerfile .
```

## Overrides

Default manifests are loaded from `baseline/manifests/` in a checkout, with packaged fallback manifests under `evolink_bench/baselines/manifests/`. Pass changes through `--baseline-config`. Set model/provider options, environment variable names, and image explicitly. If a custom command contains an image literal, bind both its image position and the configured image consistently; the runtime's deployment checks reject a mismatch.

Hermes uses a dedicated seed configuration directory rather than your interactive home. Copy `examples/hermes-baseline.override.json` to a local file and set `state.seed_from` to a clean directory containing its `config.yaml`. Select provider/model there and in the adapter options as required. Do not seed personal sessions or secrets into benchmark state.

The evaluated source includes the command-timeout alignment in `evolink_bench/baselines/hermes_bridge.py`. Per-experiment container overlays and provider-specific native patches are not automatically recreated by the default image recipes. A fresh image build is therefore a new deployment requiring validation, not a byte-identical reconstruction of every historical container. See [release notes](release.md).

## Session and learning boundaries

Read each manifest's `state`, `evolution`, `options`, and capabilities. An execution session is not synonymous with learning state. Adapters that implement no post-turn learner must report their update boundary appropriately; do not infer an update merely from the selected condition.

## Additional integrations

SkillOpt, Trace2Skill, DeepSeek Harness, and ZCode adapters and examples remain available. Their external source, initial skills, native build products, and dependencies must be supplied separately. This source release does not bundle those third-party datasets or assert that all optional integrations share the final five-system evaluation scope.
