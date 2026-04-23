# Memco Audit Evidence Appendix

Date: 2026-04-24
Status: historical pre-remediation evidence appendix, not current release verdict.
Current release verdict lives in `docs/2026-04-24_memco_release_closure.md`.
Audit package index: `docs/2026-04-24_memco_audit_package_index.md`
Source audit: `docs/2026-04-24_memco_final_release_audit.md`
Russian executive summary: `docs/2026-04-24_memco_final_release_audit_ru.md`
Contract compliance matrix: `docs/2026-04-24_memco_contract_compliance_matrix.md`
Remediation plan: `docs/2026-04-24_memco_release_remediation_plan.md`
Blocker ticket pack: `docs/2026-04-24_memco_blocker_ticket_pack.md`
Docs status map: `docs/2026-04-24_memco_docs_status_map.md`
Purpose: reproducible evidence for the private-release `NO-GO` verdict.

This appendix is not a separate product verdict. It records the concrete checks behind the audit so the next programmer-agent can fix the blockers without re-litigating scope.

## Scope Boundary

The audit used the narrowed repo-local contract:

- local/private/operator-controlled/review-gated
- one technical owner/operator
- no public SaaS registration/profile/billing requirement
- Hermes/API service path still required to be operational for the real intended use

The one-user condition removes public SaaS product requirements. It does not remove the need for:

- stable API actor credentials
- passing tests
- fresh release artifacts for the current checkout
- live provider readiness for release claims
- canonical Postgres readiness for the active local release path

## Commands Run

### Full suite

Command:

```bash
cd /Users/martin/memco
uv run pytest -q
```

Observed result:

```text
2 failed, 345 passed in 12.03s
```

Failing tests:

```text
tests/test_docs_contract.py::test_implementation_notes_use_original_brief_language
tests/test_docs_contract.py::test_current_contract_explicitly_scopes_out_whatsapp_and_telegram
```

Grounded interpretation:

- tests still read `IMPLEMENTATION_NOTES.md` at repo root
- root `IMPLEMENTATION_NOTES.md` is deleted in the current working tree
- untracked `docs/IMPLEMENTATION_NOTES.md` exists, but docs/tests are not consistently moved to that path

This is a release blocker because the project's own regression suite is red.

### Private core-loop subset

Command:

```bash
uv run pytest -q \
  tests/test_ingest_service.py \
  tests/test_cli_smoke.py \
  tests/test_retrieval_logging.py \
  tests/test_fact_lifecycle_rollback.py
```

Observed result:

```text
38 passed in 2.04s
```

Grounded interpretation:

- the core local memory loop is not empty or fake
- ingestion, CLI smoke, retrieval logging, and rollback behavior have useful coverage
- this does not prove final Hermes/API-backed release readiness

### Eval harness

Command:

```bash
tmpdir=$(mktemp -d)
uv run memco eval-run --root "$tmpdir"
```

Observed result:

```text
total=27
passed=27
failed=0
pass_rate=1.0
```

Grounded interpretation:

- fixture/private acceptance harness is green
- token accounting is tracked
- this remains fixture/eval evidence, not live provider release proof

### Quick release check

Command:

```bash
uv run memco release-check \
  --project-root /Users/martin/memco \
  --output /tmp/memco-audit-release-check.json
```

Observed top-level result:

```json
{
  "ok": false,
  "generated_at": "2026-04-23T19:34:41Z",
  "gate_type": "repo_local_release"
}
```

Observed failed/skipped steps:

```text
runtime_policy.ok=false
runtime_policy.reason=openai-compatible provider is missing api_key
pytest_gate.ok=false
acceptance_artifact.skipped=true
acceptance_artifact.reason=pytest_gate_failed
```

Grounded interpretation:

- fail-closed behavior is working
- the current shell is not release-ready because live provider config is absent
- the release check also inherits the docs-contract pytest failure

### Release-grade readiness check

Command:

```bash
uv run memco release-readiness-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres' \
  --output /tmp/memco-audit-release-readiness.json
```

Observed top-level result:

```json
{
  "ok": false,
  "generated_at": "2026-04-23T19:34:49Z",
  "gate_type": "release_readiness"
}
```

Observed failed/skipped steps:

```text
runtime_policy.ok=false
runtime_policy.reason=openai-compatible provider is missing api_key
pytest_gate.ok=false
acceptance_artifact.skipped=true
acceptance_artifact.reason=pytest_gate_failed
postgres_smoke.skipped=true
postgres_smoke.reason=prior_gate_failed
benchmark_artifact.skipped=true
benchmark_artifact.reason=prior_gate_failed
live_operator_smoke.skipped=true
live_operator_smoke.reason=live_smoke_required_for_release_claim
```

Grounded interpretation:

- this is the release-grade path for the current private operator-controlled claim
- it is red in the current checkout/shell
- prior green artifacts cannot override this current red result

### Operator preflight

Command:

```bash
uv run memco operator-preflight --project-root /Users/martin/memco
```

Observed result:

```text
ok=false
runtime_policy=false
operator_env=false
reason=openai-compatible provider is missing api_key
missing live_llm_credentials
db_reachability=ok
backup_path=ok
```

Grounded interpretation:

- local Postgres and backup path are not the blocker
- live provider/operator env is the blocker in a plain shell

## Artifact Freshness Check

Command:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from memco.artifact_semantics import evaluate_artifact_freshness

root = Path('/Users/martin/memco')
for name in [
    'release-check-current.json',
    'release-check-postgres-current.json',
    'strict-release-check-current.json',
    'release-readiness-check-current.json',
    'live-operator-smoke-current.json',
    'repo-local-status-current.json',
]:
    path = root / 'var' / 'reports' / name
    payload = json.loads(path.read_text())
    result = evaluate_artifact_freshness(payload, project_root=root)
    print(name, result['status'], result['current_for_checkout_config'])
PY
```

Observed result:

```text
release-check-current.json stale False
release-check-postgres-current.json stale False
strict-release-check-current.json stale False
release-readiness-check-current.json stale False
live-operator-smoke-current.json stale False
repo-local-status-current.json stale False
```

Grounded interpretation:

- existing green artifacts are historical evidence
- they are not current proof for the dirty checkout audited on 2026-04-24

## Actor Credential Reproduction

### Raw config lacks persisted actor policies

Current local config:

```text
var/config/settings.yaml
```

Observed relevant lines:

```yaml
api:
  host: 127.0.0.1
  port: 8788
  auth_token: memco-local-operator-token
```

There is no persisted `api.actor_policies` block in the raw YAML.

### Default actor tokens are regenerated

Command:

```bash
uv run python - <<'PY'
import yaml
from pathlib import Path
from memco.config import load_settings

root = Path('/Users/martin/memco')
raw = yaml.safe_load((root / 'var/config/settings.yaml').read_text()) or {}
a = load_settings(root)
b = load_settings(root)
print('raw_config_has_api_actor_policies', 'actor_policies' in raw.get('api', {}))
print('settings_materializes_default_actor_policies', sorted(a.api.actor_policies))
print(
    'tokens_stable_between_loads',
    {k: a.api.actor_policies[k].auth_token == b.api.actor_policies[k].auth_token for k in sorted(a.api.actor_policies)},
)
PY
```

Observed result:

```text
raw_config_has_api_actor_policies False
settings_materializes_default_actor_policies ['dev-owner', 'eval-runner', 'maintenance-admin', 'system']
tokens_stable_between_loads {'dev-owner': False, 'eval-runner': False, 'maintenance-admin': False, 'system': False}
```

Grounded interpretation:

- the app materializes default actors
- those default actors use generated tokens
- without persistence, a caller can build an actor from one load and fail against another load

### API route failure

Command:

```bash
uv run python - <<'PY'
from fastapi.testclient import TestClient
from memco.api.app import app
from memco.config import load_settings
from memco.models.retrieval import ActorContext

settings = load_settings('/Users/martin/memco')
policy = settings.api.actor_policies['dev-owner']
actor = ActorContext(
    actor_id='dev-owner',
    actor_type=policy.actor_type,
    auth_token=policy.auth_token,
    can_view_sensitive=True,
)
client = TestClient(app)
headers = {'x-memco-token': settings.api.auth_token}
missing = client.post('/v1/retrieve', headers=headers, json={'query': 'Alice lives in Lisbon'})
with_actor = client.post('/v1/retrieve', headers=headers, json={'query': 'Alice lives in Lisbon', 'actor': actor.model_dump()})
print('missing_actor_status', missing.status_code, missing.json().get('detail'))
print('prior_load_actor_status', with_actor.status_code, with_actor.json().get('detail'))
PY
```

Observed result:

```text
missing_actor_status 422 Actor context is required for /v1/retrieve.
prior_load_actor_status 403 Invalid actor credentials for /v1/retrieve.
```

Grounded interpretation:

- the route correctly requires actor context
- the real-root actor credential path is unstable unless actor policies are persisted or otherwise made stable
- this directly affects the intended Hermes/API use case

## Code Evidence

### Actor policy defaults generate tokens

`src/memco/config.py`:

```text
25 def _default_actor_policies() -> dict[str, ApiActorPolicy]:
27     "system": ApiActorPolicy(... auth_token=secrets.token_hex(16) ...)
28     "dev-owner": ApiActorPolicy(... auth_token=secrets.token_hex(16) ...)
29     "maintenance-admin": ApiActorPolicy(... auth_token=secrets.token_hex(16) ...)
30     "eval-runner": ApiActorPolicy(... auth_token=secrets.token_hex(16) ...)
39 actor_policies: dict[str, ApiActorPolicy] = Field(default_factory=_default_actor_policies)
```

### API reloads settings per request

`src/memco/api/deps.py`:

```text
10 def get_settings():
11     settings = load_settings()
12     ensure_runtime(settings)
13     return settings
```

### Actor credentials are checked against the per-request policy

`src/memco/api/deps.py`:

```text
74 policy = settings.api.actor_policies.get(actor.actor_id)
85 if actor.auth_token != policy.auth_token:
86     raise HTTPException(
88         detail=f"Invalid actor credentials for {route_label}.",
```

### Retrieve requires actor context

`src/memco/api/routes/retrieval.py`:

```text
21 actor = resolve_actor_context(
24     route_label="/v1/retrieve",
25     allowed_actor_types={"owner", "system"},
26     require_actor=True,
```

### Ingest pipeline requires actor context

`src/memco/api/routes/ingest.py`:

```text
87 resolve_actor_context(
90     route_label="/v1/ingest/pipeline",
91     allowed_actor_types={"owner", "admin", "system"},
92     require_actor=True,
```

## Documentation Evidence

### README HTTP pipeline examples omit actor

`README.md`:

```text
125 There is now a matching HTTP path for the same one-shot load:
128 curl -sS http://127.0.0.1:8788/v1/ingest/pipeline \
130   -d '{
131     "workspace": "default",
132     "path": "/absolute/path/to/conversation.json",
...
140 If you prefer inline text instead of a file path:
143 curl -sS http://127.0.0.1:8788/v1/ingest/pipeline \
145   -d '{
146     "workspace": "default",
147     "text": "Alice: I moved to Lisbon.",
```

But the route requires `actor`, so these examples are incomplete for real API use.

### Active docs still point to root IMPLEMENTATION_NOTES.md

Examples:

```text
README.md:51
docs/synthius_mem_execution_brief.md:23
docs/synthius_mem_execution_brief.md:132
docs/2026-04-21_memco_release_readiness_gate.md:68
tests/test_docs_contract.py:68
tests/test_docs_contract.py:170
```

Grounded interpretation:

- moving the file into `docs/` without updating all references and tests is incomplete
- restoring the root file is the lower-risk fix

## Dirty Worktree Context

Current status after adding audit artifacts includes pre-existing tracked modifications plus these audit files:

```text
?? docs/2026-04-24_memco_final_release_audit.md
?? docs/2026-04-24_memco_release_remediation_plan.md
?? docs/2026-04-24_memco_audit_evidence_appendix.md
```

Do not treat this appendix as proof that the repo was clean. The dirty checkout is part of the reason stale artifacts cannot be accepted as current release proof.

## Release Decision From Evidence

Private single-user scope removes these as blockers:

- public registration
- public user profiles
- billing
- org/team management
- public SaaS onboarding

Private single-user scope does not remove these blockers:

- full suite red
- release-readiness gate red
- missing live provider env in the current shell
- stale green artifacts
- unstable API actor credentials in the current root
- incomplete HTTP examples for routes that require actor context

Therefore the evidence supports:

```text
Core private loop: cautiously usable for technical local testing.
Final private Hermes/API-backed release: NO-GO until the blockers above are fixed and fresh release-readiness proof is produced.
```
