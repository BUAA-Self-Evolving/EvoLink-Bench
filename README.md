# EvoLink-Bench

**A benchmark for evaluating self-evolving agents in long-horizon interdependent task streams.**

[GitHub repository](https://github.com/BUAA-Self-Evolving/EvoLink-Bench) · [中文说明](docs/README.zh-CN.md) · [Dataset access](docs/datasets.md) · [Reproduction](docs/reproduction.md) · [Publication guide](docs/publishing.md) · [Agent setup](docs/baselines.md) · [Evaluation protocol](docs/protocol.md)

## Overview

EvoLink-Bench evaluates whether an agent can retain, correct, and reuse information and execution experience across ordered task streams. Later tasks may depend on facts, decisions, files, code, or experimental results from earlier tasks.

The benchmark separates ordinary task execution and within-task retries from explicit post-turn updates. It records task outcomes together with evidence about attempted updates, committed state changes, and later transfer. Reset, Frozen, and Evolving conditions expose different persistence and update settings. Score differences between conditions are descriptive comparisons and do not by themselves establish a causal learning effect.

## Benchmark design

| Level | Evaluation focus | Typical tasks and measures |
| --- | --- | --- |
| **L1: factual evolution** | Acquiring, retaining, correcting, and applying language-expressible knowledge across tasks. | Facts, user preferences, and constraints evaluated with the applicable task verifier. |
| **L2: task-level capability evolution** | Developing and reusing execution-based capabilities across tasks. | Artifact production, code revision, and experimental workflows evaluated with the package's native verifier and rubric. |

Task streams are ordered and may contain explicit dependencies. A later task can reuse or revise information and artifacts from an earlier task after intervening turns. Temporal spacing and dependency structure are properties of the stream protocol, rather than additional evaluation levels.

| Condition | Workspace and permitted agent state | Explicit post-turn update |
| --- | --- | --- |
| **Reset** | Reinitialized before each turn | Disabled |
| **Frozen** | Retained across turns | Disabled |
| **Evolving** | Retained across turns | Enabled when implemented by the adapter |

An explicit post-turn update is an adapter-defined learning procedure that runs after task execution using the trajectory and feedback available to that adapter. Files created during ordinary execution are workspace artifacts. Their persistence alone does not establish a learning update.

## Scope and data access

This source repository contains the evaluator, adapters, schemas, examples, and offline tests. The offline examples run from a source checkout. Reproducing a reported experiment also requires the corresponding authorized task package, grading assets, and runtime configuration. See the dataset access and reproduction guides for those prerequisites.

The L1-Arena compatibility package is derived from ClawArena's `clawarena-real` dataset at commit `630efd8a0d1dc8189718226c7da158cbe4c2fe64`. The derived package contains 23 streams, 423 turns, including 377 upstream execution-check rounds and 46 added distractor turns. See [THIRD_PARTY.md](THIRD_PARTY.md) and [Dataset access](docs/datasets.md) before distributing any derived data.

L2 package contents and redistribution terms vary by source. The public source release does not include private answers or hidden verifiers. Dataset cards and release manifests must identify the exact package revision, file list, checksums, and applicable licenses before publication.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install 'pytest>=8.3,<9' 'jsonschema>=4.23,<5'
```

## Offline smoke test

The smoke specification uses local scripted components and does not call a model provider.

```powershell
evolink-bench --spec examples\smoke.json --output runs\smoke
python -m pytest -q
python -m compileall -q evolink_bench baseline\adapters tools tests
```

## License

Project-authored code is released under the MIT License. Third-party code, data, task assets, and notices remain subject to their own terms. See [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md).

## Citation

Please cite EvoLink-Bench using the software citation in [CITATION.cff](CITATION.cff).
