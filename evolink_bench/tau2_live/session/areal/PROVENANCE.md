# Provenance

This compatibility module was derived from the AReaL τ² integration under the `examples/tau2/` tree of the `codex-sao-math` branch.

- Source repository: AReaL
- Source branch: `codex/sao-math`
- Source revision: `979f4221a06ce040a36b7bd1dadd5f8a91324add`
- Upstream tau2-bench license: MIT.
- Upstream tau2-bench revision: `b7ea9074c1cba482b30687fecdb5c8425fd6f619`
- AReaL license: Apache-2.0

| File | Source path | Change |
| --- | --- | --- |
| `user_simulator.py` | `user_simulator.py` | Replaced the AReaL logging import with the Python standard-library logging module. |
| `benchmark_variant.py` | `benchmark_variant.py` | No source change. |
| `benchmark_fixes.json` | `benchmark_fixes.json` | Retains the pinned upstream reward bases and task replacements. The evaluated snapshot also includes Retail audit patches and training exclusions. |
| `contracts.py` | `contracts.py` | No source change. |
| `runner.py` | `agent.py` (`Tau2Runner` and helpers) | See the module docstring for the integration adaptation. |

The AReaL decisions governing these semantics are ADR 0001, ADR 0009, and ADR 0010 in the upstream repository. Preserve the upstream license and notices when redistributing derived material.
