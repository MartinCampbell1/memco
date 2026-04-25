Historical document. Not current verdict.
Current verdict: see docs/CURRENT_STATUS.md

# Memco: итоговый аудит релизной готовности

Дата: 2026-04-24
Аудитор: Codex
Status: historical pre-remediation audit baseline, not current release verdict.
Current verdict: see `docs/CURRENT_STATUS.md`.
Индекс audit-пакета: `docs/2026-04-24_memco_audit_package_index.md`
Источник полного аудита: `docs/2026-04-24_memco_final_release_audit.md`
Матрица соответствия: `docs/2026-04-24_memco_contract_compliance_matrix.md`
Evidence appendix: `docs/2026-04-24_memco_audit_evidence_appendix.md`
План исправлений: `docs/2026-04-24_memco_release_remediation_plan.md`
Ticket pack: `docs/2026-04-24_memco_blocker_ticket_pack.md`
Карта статусов docs: `docs/2026-04-24_memco_docs_status_map.md`

## Короткий вердикт

**NO-GO для честного private Hermes/API-backed использования прямо сейчас.**

Это не значит, что Memco пустой или фейковый. Наоборот: базовый private memory loop реально реализован и частично хорошо покрыт тестами. Но текущий checkout нельзя честно назвать полностью рабочим private-релизом для твоего реального сценария, где Memco должен быть подключен к Hermes/agent path через API/service.

## Ответ на главный вопрос

Если продукт предназначен только для одного человека, то не нужны:

- публичная регистрация
- публичные профили пользователей
- billing
- organization/team management
- SaaS onboarding
- полноценная multi-user UX

Но single-user режим не отменяет:

- прохождение test suite
- стабильные credentials для API actor context
- рабочий Hermes/API путь
- live provider readiness
- свежие release artifacts для текущего checkout
- честный release-readiness gate

Именно по этим пунктам сейчас есть blockers.

## Что реально работает

Рабочие части:

- CLI/dev memory loop можно осторожно тестировать локально
- ingestion/retrieval/rollback/refusal path не выглядит пустым
- private core subset зеленый:

```text
38 passed in 2.04s
```

- eval harness зеленый на fixture/private path:

```text
total=27
passed=27
failed=0
pass_rate=1.0
```

- fail-closed runtime behavior работает: без live provider key система не делает ложный green release claim
- local Postgres и backup path сами по себе не являются главным blocker

## Почему это еще не GO

### 1. Full test suite красный

Команда:

```bash
uv run pytest -q
```

Результат:

```text
2 failed, 345 passed
```

Причина: root `IMPLEMENTATION_NOTES.md` удален, но docs-contract tests и часть документации все еще ожидают этот файл именно в root. При этом появился untracked `docs/IMPLEMENTATION_NOTES.md`, но перенос не доведен консистентно.

Пока full suite красный, утверждение "все выполнено и все функционирует" не проходит аудит.

### 2. Release-grade gate красный

Команда:

```bash
uv run memco release-readiness-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'
```

Результат:

```text
ok=false
runtime_policy.reason=openai-compatible provider is missing api_key
pytest_gate.ok=false
live_operator_smoke.skipped=true
live_operator_smoke.reason=live_smoke_required_for_release_claim
```

Это главный release-grade gate для текущего private/operator-controlled claim. Он сейчас не зеленый.

### 3. Старые green artifacts stale

В `var/reports/*current*` есть зеленые артефакты, включая release/readiness/live-smoke. Но при текущей проверке они stale относительно dirty checkout.

Проверенные файлы:

- `release-check-current.json`
- `release-check-postgres-current.json`
- `strict-release-check-current.json`
- `release-readiness-check-current.json`
- `live-operator-smoke-current.json`
- `repo-local-status-current.json`

Все показали:

```text
status=stale
current_for_checkout_config=False
```

Значит их нельзя использовать как доказательство текущей релизной готовности.

### 4. API actor credentials нестабильны в текущем root

Текущий `var/config/settings.yaml` не хранит `api.actor_policies`.

Код генерирует default actor tokens через `secrets.token_hex(16)`. Поэтому две загрузки settings дают разные токены:

```text
tokens_stable_between_loads {'dev-owner': False, 'eval-runner': False, 'maintenance-admin': False, 'system': False}
```

Практический эффект:

```text
missing_actor_status 422 Actor context is required for /v1/retrieve.
prior_load_actor_status 403 Invalid actor credentials for /v1/retrieve.
```

Это критично именно для твоего реального сценария: Memco должен использоваться через Hermes/API, а не только через CLI.

### 5. README HTTP examples неполные

README показывает `/v1/ingest/pipeline` curl examples без `actor`, но route требует actor context:

```text
route_label="/v1/ingest/pipeline"
require_actor=True
```

То есть человек, следующий README, может получить нерабочий API flow.

## Оценка отчета programmer-agent

Фраза "все выполнено и все функционирует" сейчас некорректна.

Более точная формулировка была бы:

```text
Core private memory loop materially implemented and fixture/private checks are green,
but current checkout is not release-ready for Hermes/API-backed private use.
```

## Что не является blocker

Для твоего one-user режима не считаю blocker:

- отсутствие публичной регистрации
- отсутствие профилей пользователей как SaaS-фичи
- отсутствие billing
- отсутствие публичного onboarding
- отсутствие полноценной multi-tenant модели

Также strict original brief по Docker Compose остается `NO-GO` как reference-track, но это не blocker для твоего accepted no-Docker local workflow, если документация честно фиксирует waiver/superseding.

## Что нужно сделать до честного GO

Минимальный список:

1. Починить `IMPLEMENTATION_NOTES.md` path mismatch.
2. Добиться `uv run pytest -q` green.
3. Сделать API actor credentials стабильными для Hermes/API path.
4. Исправить HTTP docs/examples под обязательный `actor`.
5. Пометить старые планы/статусы как historical/superseded, если они противоречат текущему release state.
6. Пересобрать свежие release artifacts на текущем checkout.
7. Запустить release-grade command с live provider env и live smoke:

```bash
MEMCO_RUN_LIVE_SMOKE=1 \
MEMCO_API_TOKEN='...' \
MEMCO_LLM_API_KEY='...' \
uv run memco release-readiness-check \
  --project-root /Users/martin/memco \
  --postgres-database-url 'postgresql://martin@127.0.0.1:5432/postgres'
```

8. Проверить, что новый artifact свежий относительно текущего checkout/config.

## Финальный ответ

**Можно ли пользоваться сейчас?**

Только осторожно как техническим local CLI/dev prototype.

**Можно ли считать продукт полностью соответствующим документации под single-user условие?**

Нет. Single-user scope валиден, но текущая реализация не проходит собственные release criteria для Hermes/API-backed use.

**Может ли продукт быть использован как твоя рабочая private memory service прямо сейчас?**

Я бы не включал его в реальный агентский контур до фикса P0 blockers и свежего green `release-readiness-check`.
