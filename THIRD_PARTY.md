# Third-party sources and notices

Project-authored code is released under the MIT License in the root `LICENSE` file. Third-party code, datasets, task assets, and notices retain their applicable licenses and redistribution conditions. Inclusion in this repository does not relicense upstream material.

## Dataset and benchmark sources

| Source | Used in | License status |
| --- | --- | --- |
| ClawArena `clawarena-real` | L1-Arena compatibility package | Upstream repository is MIT. The pinned source commit is `630efd8a0d1dc8189718226c7da158cbe4c2fe64`. Retain `licenses/ClawArena-LICENSE`. Review embedded assets separately. |
| AReaL τ² integration | L2 tau2 compatibility code | Apache-2.0. See [provenance](evolink_bench/tau2_live/session/areal/PROVENANCE.md) and the [AReaL license](licenses/AReaL-LICENSE). |
| tau2-bench | L2 tau2 compatibility code | MIT at the pinned revision. See the [tau2-bench license](licenses/tau2-bench-LICENSE). Dataset releases require a separate component manifest. |
| SICK, Titanic, stock-data sources, and other L2 inputs | L2 task packages | Redistribution terms are package-specific and must be confirmed from the exact source release before public upload. |

## Evaluated baseline sources

| Baseline | Repository | Pinned revision |
| --- | --- | --- |
| Hermes | https://github.com/NousResearch/hermes-agent | `53873bfae5dfdd5f1af5cb6203a441f6e75330c1` |
| Prime Agent | https://github.com/PrimeIntellect-ai/prime-agent | `163dd5798cd40e86b540aa9ecb68201920a83a1b` |
| Adaptive Auto-Harness | https://github.com/A-EVO-Lab/a-evolve | `17bc9ebb7d4d142af1b109b43ef160031967cc9a` |
| OpenCode | https://github.com/anomalyco/opencode | `df23b7f9488a38e6f8064a0739d4f8cde86d7cfb` |
| Codex | https://github.com/openai/codex | `cc7ba33601286a751477832b01de7b6f8de0dd9c` |
| DeepSeek Harness | https://github.com/deepseek-ai/deepseek-harness | `d743267388641bc76f17c45ce8b4c231aed1d32c` |
| ZCode | https://github.com/zai-org/ZCode | `aac4755666d09fdcd70272fcf063c077a639015f` |

These entries document provenance for evaluated integrations. They do not imply that complete upstream repositories or model assets are bundled here.

## Compatibility modules

The `evolink_bench/tau2_live/` compatibility modules include source-derived integration code. Their file-level provenance and changes are recorded in `evolink_bench/tau2_live/session/areal/PROVENANCE.md`. Review that record and retain all required notices before redistributing derived task assets.

Do not publish dependency trees, model weights, private task data, hidden verifiers, credentials, generated reports, or institutional emblems without explicit permission and a matching license record.
