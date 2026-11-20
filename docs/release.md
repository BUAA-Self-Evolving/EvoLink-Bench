# Release 0.1.0

This release packages the EvoLink-Bench evaluator, adapters, schemas, examples, offline tests, and publication documentation.

## Included

- Python package `evolink_bench` and CLI `evolink-bench`.
- L1 and L2 compatibility entry points, baseline adapters, schemas, and scripted examples.
- Offline test and smoke-test configuration.
- MIT project license and third-party provenance notices.

## Excluded

Private task statements, answers, hidden graders, credentials, run logs, checkpoints, model caches, institutional files, and historical experiment outputs are excluded from the source release. Dataset publication requires a separate package review and a dataset-specific license and access statement.

## Validation

Use the offline smoke test and test suite to verify a local installation. Release assets include SHA-256 checksums. See the [publication guide](publishing.md) for build and verification commands.

## Known limitations

Some optional integrations require external source checkouts, containers, or private data packages. The source package does not certify those external prerequisites. The optional fast checkpoint path uses POSIX filesystem semantics. Windows uses the standard ZIP checkpoint path. Standard post-turn checkpoint resume is supported. Recovery records tied to individual historical experiments require their original environment.

## Publication status

The canonical source repository is [BUAA-Self-Evolving/EvoLink-Bench](https://github.com/BUAA-Self-Evolving/EvoLink-Bench). A Hugging Face dataset repository is published only after its final repository ID, file manifest, checksums, and redistribution terms have been recorded.
