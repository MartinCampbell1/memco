# Private Pilot Runbook

Status: active runbook for private single-user agent-memory pilots.

Scope: local/private/operator-controlled/review-gated Memco usage before automatic memory injection is allowed.

## Gate Before Pilot

Start a pilot only after the local operator shell has a fresh green personal-memory eval artifact:

```bash
uv run memco eval personal-memory --goldens eval/personal_memory_goldens --output var/reports/personal-memory-eval-current.json
```

The artifact must report `ok: true`, `failed: 0`, and all policy checks green. A release or readiness artifact does not replace this pilot-specific gate.

## Required Sequence

1. Start with synthetic data.

   Run the personal-memory eval and at least one throwaway synthetic root before loading private user data. Use the synthetic run to verify retrieval, refusal, evidence ids, rollback, and logs without risking real memory contamination.

2. Run extraction with manual review.

   For the first real data load, use the explicit staged flow instead of auto-publishing through a pipeline shortcut:

   ```bash
   uv run memco import /absolute/path/to/source.json --source-type json --root "$ROOT"
   uv run memco conversation-import --latest-source --root "$ROOT"
   uv run memco candidate-extract --latest-conversation --root "$ROOT"
   uv run memco review-list --status pending --root "$ROOT"
   ```

   Resolve speakerless, social/family, sensitive, low-confidence, and ambiguous candidates manually before they are eligible for publication.

3. Publish only reviewed facts.

   Publish only facts the operator has reviewed or explicitly approved. In mixed workspaces, scope shortcuts with `--person-slug` and `--domain`; do not blindly publish the newest candidate.

   ```bash
   uv run memco review-resolve approved --latest-review --person-slug alice --publish --reason "pilot reviewed" --root "$ROOT"
   uv run memco candidate-publish --candidate-id CANDIDATE_ID --root "$ROOT"
   ```

4. Use agents in retrieval-only mode first.

   During the first pilot stage, agents may call `retrieve` or `/v1/retrieve` and may cite returned fact/evidence ids. They must not automatically inject memories into prompts, write new facts, or treat unsupported answers as facts.

   ```bash
   uv run memco retrieve "Where does Alice live?" alice --detail-policy core_only --root "$ROOT"
   uv run memco retrieve "Does Alice work at Stripe?" alice --detail-policy core_only --root "$ROOT"
   ```

5. Log all unsupported claims.

   Keep retrieval logs enabled. Review unsupported, contradicted, ambiguous, and subject-mismatch retrievals as pilot incidents, even when refusal behavior was correct.

   ```bash
   uv run memco retrieval-log-list --person-slug alice --root "$ROOT"
   ```

   Retrieval logs are redacted by design. If the operator needs the original query text for a private incident note, keep that note local and out of shared audit archives.

6. Run a weekly audit of wrong or low-confidence facts.

   Once per week, review low-confidence facts, sensitive social/family facts, recent rollback operations, and retrieval incidents. Correct wrong facts by superseding or rolling back through the fact lifecycle instead of editing the database directly.

   ```bash
   uv run memco fact-list --person-slug alice --root "$ROOT"
   uv run memco fact-operations --latest-target-fact --root "$ROOT"
   uv run memco fact-rollback --latest-operation --reason "pilot weekly audit correction" --root "$ROOT"
   ```

7. Enable automatic memory injection only after 2-3 clean weeks.

   Automatic memory injection is allowed only after at least 2-3 weeks with no P0 incidents, no unresolved wrong-fact reports, no cross-person contamination, and no unsupported premise answered as fact. Until then, keep agent usage retrieval-only and evidence-cited.

## P0 Pilot Incidents

Treat any of the following as P0 and disable automatic injection if it was enabled:

- a false or unsupported premise is presented as confirmed memory
- a fact from one person appears in another person’s answer
- sensitive social/family/private data is exposed outside the intended actor scope
- an agent writes or publishes a fact without review during the manual-review phase
- a rollback/update fails to preserve the current truth state

After a P0 incident, return to retrieval-only mode, fix or roll back the affected facts, rerun the personal-memory eval gate, and keep a private incident note outside tracked source.
