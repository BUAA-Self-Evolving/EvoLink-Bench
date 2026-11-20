# Running evaluations

Run commands from the repository root. Install the project in an isolated Python environment first. Native evaluations use Docker on Linux and may invoke paid model services. The scripted `examples/smoke.json` example is offline.

## Credentials and configuration

Set credentials in your shell environment, never in a committed JSON file:

```bash
export TRIEVO_API_KEY='your-api-key'
export TRIEVO_BASE_URL='https://your-provider.example/v1'
export TRIEVO_MODEL='your-model-id'
```

These variables configure the generic OpenAI-compatible runtime. Native adapters also have their own `options` fields. Supply an explicit override based on the corresponding `examples/*override.json`; inspect `api_key_env`, `base_url`, `model`, learning policy, and time limits. An example's model name and timeouts are illustrative, not universal experimental defaults. Codex requires an endpoint implementing its native API contract.

The generic model example can be run with:

```bash
evolink-bench --spec examples/deepseek_smoke.json --output runs/model-example
```

Unlike the scripted smoke, this makes real model requests when configured. Custom provider profiles and relays are optional advanced deployment tools; they are not required for the offline quick start.

## Task and verifier images

```bash
docker build -t evolink-ubuntu:22.04 sandbox/ubuntu
docker build -t evolink-l2:0.1 -f sandbox/l2/Dockerfile .
```

The L2 task package may require a specific verifier/browser image or a runtime profile. Build and select those exact requirements. Do not increase limits to work around an environment error.

## L1 Arena

```bash
python -m evolink_bench.l1_arena_compat --package /path/to/l1 --inspect
python -m evolink_bench.l1_arena_compat \
  --package /path/to/l1 --stream stream-1 --turns turn1,turn2 \
  --baseline hermes --baseline-config /path/to/hermes.override.json \
  --condition frozen --max-total-tokens 20000000 \
  --output runs/hermes-l1-frozen
```

Use turn IDs from the package and an explicit condition. The L1 CLI defaults to the first turn if no turn list is supplied. Do not assume it runs a whole stream automatically. Its package adapter declares the public execution limits; native request retry counters and recorded usage still need separate inspection.

## L2 TaskStream

```bash
python -m evolink_bench.l2_compat --package /path/to/l2 --inspect
python -m evolink_bench.l2_compat \
  --package /path/to/l2 --stream YOUR_STREAM_ID \
  --baseline hermes --baseline-config /path/to/hermes.override.json \
  --condition evolving --image evolink-l2:0.1 \
  --allow-generated-code --max-total-tokens 20000000 \
  --output runs/hermes-l2-evolving
```

`--allow-generated-code` is an explicit opt-in to task-owned executable evaluation. Docker containment does not make untrusted code intrinsically safe.

For panel-aware packages, provide the package's `--panel-id`, `--panel-manifest-sha256`, and `--panel-streams` bindings. Newer pool-aware packages may also require `--pool-id`, pool/package digests, and runtime-profile digests. The runtime refuses inconsistent bindings. The advanced matrix driver can derive these from the selected manifest; inspect its `--help` and use explicit package/config paths rather than an old experiment preset.

## Resume and evidence

The L1/L2 CLIs accept `--resume-checkpoint` for a validated post-turn checkpoint. Finished turns are inherited; later turns execute. A saved pending judge response and an interrupted agent interaction are different recovery cases. Do not use a general resume command to blindly replay tools or previously paid replies.

Recovery utilities retained under `tools/` have strict identity, prefix, authorization, or evidence requirements. Some support specific historical formats and are not generic retry commands. Review their preconditions before use. These utilities do not automatically migrate historical archives or rerun recorded experiments.

## Summaries

Keep the report's task reward separate from acceptance and update outcome. A task may have a valid grade while a later learning proposal is rejected. Preserve exact denominator and panel selection, and do not silently use missing or ungraded outcomes as numeric zero.
