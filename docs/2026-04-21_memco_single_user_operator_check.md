# Memco Single-User Operator Check

Date: 2026-04-21  
Mode: clean temporary root  
Goal: verify whether one private operator can actually use the system end-to-end today

Historical note:

- This check reflects the earlier operator surface before the CLI was completed.
- It is kept as evidence of the pre-remediation operator experience.
- For the current private operator verdict, use [2026-04-21_memco_private_release_gate.md](2026-04-21_memco_private_release_gate.md).

## Result

Verdict: usable with caution

The private operator path works in practice, but it is not yet a polished one-surface workflow.

## Flow executed

Environment:

- temp root: `/tmp/memco-operator-FfM8ML`
- input file: `/tmp/memco-operator-flow.json`

Successful steps:

1. `uv run memco init-db --root /tmp/memco-operator-FfM8ML`
2. `uv run memco person-upsert Martin --workspace default --slug martin --alias Martin --root /tmp/memco-operator-FfM8ML`
3. `uv run memco import /tmp/memco-operator-flow.json --source-type json --workspace default --root /tmp/memco-operator-FfM8ML`
4. conversation import via service call
5. `uv run memco candidate-extract 1 --workspace default --root /tmp/memco-operator-FfM8ML`
6. `uv run memco candidate-publish ...`
7. `uv run memco retrieve "Where does Martin live?" martin --workspace default --root /tmp/memco-operator-FfM8ML`
8. `uv run memco chat "Where does Martin live?" martin --workspace default --root /tmp/memco-operator-FfM8ML`
9. `uv run memco chat "Does Martin have a sister?" martin --workspace default --root /tmp/memco-operator-FfM8ML`

## What worked

- bootstrap
- person creation
- source import
- conversation parsing
- candidate extraction
- candidate publishing
- supported factual retrieval
- supported factual chat answer
- false-premise refusal

## What did not feel finished

- There is no dedicated CLI command for `source_id -> conversation_id`.
- That means the CLI alone is not yet a complete operator surface.
- The product still depends on understanding the internal workflow more than a finished operator tool should.

## Practical conclusion

If the only user is the repo owner and they are comfortable with a technical workflow, the system is already practically usable.

If the product is being claimed as fully complete against the execution brief, this operator check does not support that claim.
