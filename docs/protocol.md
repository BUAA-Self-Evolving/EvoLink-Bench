# Evaluation protocol

## Execution units

A **flow/stream** is an ordered sequence of **turns**. A turn may contain multiple **interactions** according to its declared limit and feedback policy. An interaction includes the agent's execution and resulting public feedback. It is not necessarily a single model request.

```text
Package -> stream -> turn -> bounded interactions -> grade
                                          -> post-turn update barrier
                                          -> next turn
```

The evaluator controls requests, permitted workspace transitions, private grading, resource budgets, and persistence conditions. Each native adapter controls its model/tool loop subject to those boundaries.

## Persistent state

Workspace artifacts and agent learning state are distinct. Agents can create task artifacts during execution. Declared learning-state changes are checked at the post-turn update barrier. Reset reinitializes permitted state; Frozen preserves it without explicit updates; Evolving enables the adapter's update procedure when supported.

State-file changes, update attempts, committed updates, and useful downstream transfer are different observations. Do not infer the last from task score alone.

## Public and private information

Public task messages, tool-visible files, and permitted feedback may enter the agent process. Hidden answers, verifier programs, private judge evidence, and recovery archives stay evaluator-side. Dataset adapters materialize the public workspace instead of mounting the complete benchmark package into the agent.

The runtime validates declared workspace inputs and state boundaries. This release retains the deployed verifier behavior, including checks that treat incidental dependency links as link metadata instead of reading another namespace.

## Budgets and failures

Model calls, tool calls, command time, episode time, update time, and token budgets are separately represented. Limits come from package metadata, adapter configuration, and run arguments; do not assume every historical cohort used an identical accounting mechanism.

Hermes command timeouts remain tool outcomes delivered back to the agent rather than automatically becoming episode-level forced zero. Episode and other hard limits remain in force. The final deployed implementation is preserved in this source release.

Strict evaluation paths stop on infrastructure/control-plane faults rather than fabricating a completed task. Preserve prior committed grades, paid replies, partial output, failure usage, and unknown usage. A checkpoint is valid only with its expected identity, completed prefix, configuration, and evidence bindings.

Recovering an evaluator from saved replies must not replay completed tasks or tool side effects. An interrupted agent request requires an explicit recovery decision; absence of a reply is not proof of absence of execution.

## Reading reports

Task reward, acceptance, execution outcome, and learning-update result are separate fields. Use the intended task/panel denominator and retain every designated result, including low scores and zeros. Do not mix overlapping panels, select only better reruns, or add inherited budget snapshots as new monetary cost.

Full specification fields are documented in [spec.md](spec.md). The runtime and schemas remain authoritative when older specification examples use legacy names.
