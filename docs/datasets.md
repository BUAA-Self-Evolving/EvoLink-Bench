# Dataset packages

Datasets and private grading assets are not bundled in this source repository, and the evaluator does not silently download them. A public data release must identify the exact package version, file manifest, checksums, redistribution terms, and access procedure.

| Input | Entry point | Required package information |
| --- | --- | --- |
| Specification JSON | `evolink-bench --spec ...` | `schema_version`, flows, turns, agents, and graders |
| L1 Arena | `python -m evolink_bench.l1_arena_compat` | `l1_arena/1.5` manifest, tools, public workspace, and task/checker files |
| Legacy L1 sessions | `python -m evolink_bench.l1_compat` | Session and turn package with original task metadata |
| L1 Life | `python -m evolink_bench.l1_life_compat` | Package-specific task and tool metadata |
| L2 TaskStream | `python -m evolink_bench.l2_compat` | Package manifest, ordered streams, public artifacts, and private verifiers |

For an L2 package with `panels.json`, use the declared panel and bindings. An overlapping parent diagnostic panel must not be aggregated with the primary short-stream panel. Preserve package-declared pools, runtime profiles, and manifest hashes.

```powershell
python -m evolink_bench.l1_arena_compat --package C:\path\to\l1 --inspect
python -m evolink_bench.l2_compat --package C:\path\to\l2 --inspect
```

Keep the full package under evaluator control. Agents receive only the task's permitted public projection and workspace. Private answers, checker scripts, judge inputs, historical traces, and state archives remain outside public agent context.

Record the package digest, stream and turn IDs, selected panel or pool, baseline revision, adapter and image digests, model configuration, limits, condition, and output evidence when reproducing a result.
