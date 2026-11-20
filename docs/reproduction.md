# Reproducing experimental results

The source checkout provides the runtime, agent adapters, and a scripted offline smoke example. It does not include a versioned paper dataset, its private grading assets, the selected experiment outputs, or a complete set of historical container images and launch configurations. A paper results table cannot currently be regenerated from this checkout alone.

## Required inputs

| Input | Needed to reproduce a result | Availability in this checkout |
| --- | --- | --- |
| Dataset | Version, package manifest and digest, access terms, stream and turn IDs, and any panel/pool bindings | Not bundled; no public download or external evaluation service is specified. See [dataset access](datasets.md). |
| Agents | Source revision, adapter revision, manifest and local overrides | Adapter manifests and recorded upstream commits are included; third-party source must be obtained separately. See [agent setup](baselines.md). |
| Model | Provider, exact model identifier/version, sampling settings and request policy | Supplied per run; the examples do not establish historical settings. |
| Execution | Condition, budgets, retries, task and learning limits, environment, image digests and runtime overlays | The runtime supports configuration, but a complete historical configuration bundle and all image digests are not provided. |
| Sampling and statistics | Stream order, run count, seeds where applicable, denominators, exclusions and aggregation procedure | Must be obtained from the relevant experiment record; these are not determined by the source checkout. |
| Results | Selected per-turn records, failure decisions, update evidence and the mapping to paper tables | A validated paper-result package and table-generation command are not included. |

Historical runs may span different runtime revisions. A freshly built default image is not automatically equivalent to a historical image. Record a run's exact package and environment identities rather than assuming that matching agent names or image tags is sufficient.

## Practical workflow

1. Obtain an authorized dataset package and inspect its manifest, checksums, public/private boundaries and declared stream and turn IDs. The inspection commands are in [datasets.md](datasets.md).
2. Check out the agent source revision and prepare its adapter and images as described in [baselines.md](baselines.md). Record image digests and any patches.
3. Record model settings, task and update limits, retry policy, condition, selected tasks, run count and seeds where used. Keep credentials out of version control and inspect generated artifacts before sharing.
4. Run the selected package using [running.md](running.md). Retain task rewards, acceptance, execution failures, update evidence and usage as separate observations.
5. Apply the documented result selection and aggregation for the target experiment, including genuine low scores, fractional scores, and explicit failure decisions. Preserve the denominator and do not select a best retry. Compare the resulting table only with the matching experimental scope.

The included offline smoke example verifies basic execution and does not test a real agent, model, or complete benchmark package. The model-backed development example in [running.md](running.md) requires credentials and Docker and has not been validated as a minimal paper reproduction. Review the [known limitations](release.md#known-limitations) before conducting evaluations.
