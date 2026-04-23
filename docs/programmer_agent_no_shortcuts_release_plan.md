# Memco: пошаговый план исправлений для агента-программиста

Status: historical remediation plan, not current release verdict.
Current verdict lives in docs/2026-04-24_memco_release_closure.md and the active gate definition lives in docs/2026-04-21_memco_release_readiness_gate.md.
Keep this file as historical implementation context; do not use it as fresh GO proof without rerunning the current gates.

## Назначение

Этот план нужен не для “красивого отчета”, а для того, чтобы довести Memco до состояния, где можно честно сказать:

- продукт можно релизить как **local private operator-controlled memory for agents**
- release claim подтвержден **текущим runtime**, а не старыми артефактами
- агент-программист не сможет “срезать углы” за счет:
  - подмены live proof фикстурами
  - опоры на старые `var/reports`
  - ослабления gate’ов
  - коммита фейковых/пустых секретов

---

## Что сейчас отделяет продукт от честного релиз-claim

### Hard blockers

1. **Текущий checkout не green as-is**
   - `var/config/settings.yaml` содержит пустой `llm.api_key`
   - текущий runtime не `release_eligible`
   - прямой `release-check` на текущем checkout падает на `runtime_policy`

2. **Live smoke не является обязательной частью релизного claim**
   - сейчас он запускается только при `MEMCO_RUN_LIVE_SMOKE=1`
   - значит можно получить “green” release path без обязательного live end-to-end proof

3. **Green reports можно спутать с текущей готовностью checkout**
   - `var/reports/*.json` фиксируют успешные прогоны из другого env-контекста
   - это полезные артефакты, но не равны “этот checkout прямо сейчас готов”

### Important but non-blocking weaknesses

4. **Benchmark все еще synthetic/internal**
   - он полезен
   - но сам по себе не доказывает реальную надежность памяти в широком production-смысле

5. **Ingest contract мягкий**
   - `parse_document()` permissive
   - unsupported `source_type` не всегда жестко режется

6. **Release wording все еще может быть слишком сильным**
   - честный scope: `local private operator-controlled agent memory`
   - нечестный scope: “полноценная универсальная память для агентов без caveat”

---

## Главные правила для агента-программиста

Ниже правила обязательны. Если агент их нарушает, задача считается проваленной даже при зеленых тестах.

### Rule 1 — Никаких фейковых секретов

Запрещено:

- коммитить реальный API key в git
- коммитить фейковый `api_key: "secret"` в runtime config ради green gate
- подменять runtime policy так, чтобы пустой ключ считался валидным

Разрешено:

- использовать env vars
- использовать локальный `.env` / shell export вне git
- использовать `.env.example` как шаблон без секретов

### Rule 2 — Нельзя считать fixture/test proof live proof’ом

Запрещено:

- считать `runtime.profile=fixture` доказательством release readiness
- считать benchmark/acceptance на mock-дорожке доказательством live operator readiness
- подменять live smoke детерминированным тестом

### Rule 3 — Нельзя ссылаться только на старые `var/reports`

Запрещено:

- говорить “все green”, если green только старые артефакты
- завершать задачу без прогона на текущем checkout

Обязательно:

- каждый release claim должен быть подкреплен **свежим прогоном**
- артефакт должен быть создан в рамках текущей сессии/шага

### Rule 4 — Нельзя ослаблять gate, чтобы получить green

Запрещено:

- убирать `runtime_policy`
- убирать `operator_safety`
- делать `storage_contract` информационным вместо обязательного
- оставлять live smoke опциональным, но писать в docs, что он обязателен

### Rule 5 — Каждый шаг закрывается только доказательством

Каждый шаг считается завершенным только если есть все 4 элемента:

1. измененный код
2. тесты
3. командный прогон
4. артефакт/вывод, который подтверждает результат

---

## Формат работы агента

Для каждого шага агент обязан выдать:

1. **Что меняю**
2. **Почему это нужно**
3. **Какие файлы меняю**
4. **Какие тесты добавляю/обновляю**
5. **Какие команды запускаю**
6. **Какой конкретно output считается доказательством**
7. **Что запрещено считать достаточным доказательством**

Если любого из этих пунктов нет — шаг не закрыт.

---

# Пошаговый план

## Шаг 0 — Зафиксировать baseline и запретить “ложно-зеленый” финал

### Цель

Сначала агент должен воспроизвести текущую правду и зафиксировать ее. Без этого он почти наверняка начнет “чинить по ощущениям”.

### Что сделать

1. На текущем checkout запустить:
   - quick release check
   - canonical postgres release check
   - strict release check
2. Записать, где именно красное:
   - `runtime_policy`
   - `release_eligible`
   - причина
3. Отдельно показать:
   - текущий `settings.yaml`
   - текущие env overrides
4. Отдельно показать, что старые `var/reports` не равны текущему runtime status.

### Файлы

- без кода, только фиксация baseline

### Обязательные команды

```bash
env PYTHONPATH=/Users/martin/memco/src /Users/martin/memco/.venv/bin/python -m memco.release_check
```

```bash
env PYTHONPATH=/Users/martin/memco/src /Users/martin/memco/.venv/bin/python - <<'PY'
from memco.config import load_settings
from memco.llm import llm_runtime_policy
s = load_settings('/Users/martin/memco')
print(s.config_path)
print(llm_runtime_policy(s))
PY
```

### Доказательство завершения

- есть сохраненный baseline output
- отдельно указано:
  - что именно green в старых артефактах
  - что именно red в текущем runtime

### Запрещенные shortcuts

- пропустить baseline
- сразу менять код “потому что и так понятно”

---

## Шаг 1 — Разделить “checkout status” и “operator-configured status”

### Цель

Система должна явно различать:

1. **current checkout status**
2. **release-configured runtime status**

Сейчас именно здесь возникает путаница.

### Что сделать

1. Ввести явное понятие двух статусов:
   - `checkout_status`
   - `operator_runtime_status`
2. Добавить в health / artifact surface поля, которые не позволят спутать:
   - статус текущего config file
   - наличие env-based live credentials
   - whether current run is config-only red but env-injected green
3. Если runtime green только за счет env injection, это должно быть явно видно.

### Файлы

- `src/memco/llm.py`
- `src/memco/release_check.py`
- `src/memco/api/routes/health.py`
- при необходимости `src/memco/local_artifacts.py`
- `tests/test_api_health.py`
- `tests/test_release_check.py`

### Нужно добиться

- чтобы релизный артефакт нельзя было прочитать как “checkout green”, если текущий config без секретов
- чтобы статус был однозначным даже для другого агента/оператора

### Доказательство завершения

- тесты на две ситуации:
  1. config red / env absent
  2. operator env green / config red
- health/release artifact показывает разницу явно

### Запрещенные shortcuts

- просто переписать docs
- оставить двусмысленный `ok: true`, который скрывает, что green только при injected env

---

## Шаг 2 — Сделать live smoke обязательным для release claim

### Цель

Нельзя выпускать релиз как “готовый”, если live smoke не был выполнен.

### Что сделать

1. Ввести один из двух обязательных вариантов:

#### Вариант A

`strict-release-check` всегда требует live smoke для release claim

#### Вариант B

появляется отдельный release-grade gate, например:

- `memco release-readiness-check`

который обязательно включает:
- runtime policy
- storage contract
- operator safety
- pytest gate
- acceptance
- postgres smoke
- benchmark
- live operator smoke

2. Старый quick/strict path можно оставить для разработки, но:
   - он не должен считаться достаточным доказательством “готово к релизу”

### Файлы

- `src/memco/release_check.py`
- CLI entrypoint, если нужен
- `tests/test_release_check.py`
- `tests/test_live_smoke.py`

### Acceptance criteria

- без live smoke release-grade gate красный
- с live smoke green only if smoke green
- release wording в коде/артефактах не говорит “готово”, если live smoke skipped

### Обязательные тесты

1. live smoke not requested -> release-grade gate red or “insufficient for release”
2. live smoke requested but env missing -> red
3. live smoke requested and successful -> green

### Запрещенные shortcuts

- оставить `MEMCO_RUN_LIVE_SMOKE=1` только как optional convenience
- считать старый strict gate достаточным для финального release claim

---

## Шаг 3 — Сделать release-ready путь воспроизводимым без ручной магии

### Цель

Чтобы другой агент не “додумывал”, как поднимать зеленый runtime, нужен один воспроизводимый путь.

### Что сделать

1. Ввести один официальный operator preflight path:
   - env vars
   - config load
   - backup path
   - DB reachability
   - provider reachability
2. Если чего-то не хватает — падать с конкретной причиной.
3. Подготовить:
   - `.env.example`
   - возможно `scripts/operator_preflight.sh` или CLI-команду
4. Дать один canonical command sequence, который может повторить любой инженер.

### Файлы

- `.env.example`
- возможно `scripts/`
- `src/memco/config.py`
- `src/memco/release_check.py`
- `tests/` для preflight path

### Acceptance criteria

- из чистого checkout можно пройти от red к green только через официальный path
- нет скрытых ручных действий “которые все и так знают”

### Доказательство завершения

- documented and testable preflight
- one command sequence works from scratch

### Запрещенные shortcuts

- “запусти локально как-нибудь”
- неявные ручные edits в `settings.yaml`
- зависимость от непубличных shell history действий

---

## Шаг 4 — Ужесточить release semantics вокруг артефактов

### Цель

Артефакты должны быть полезными, но не вводить в заблуждение.

### Что сделать

1. Все release artifacts должны содержать:
   - timestamp
   - runtime mode
   - config source
   - whether env overrides were used
   - whether live smoke ran
2. Если artifact был собран в env-injected режиме, это должно быть видно без чтения исходников.
3. Если artifact устарел относительно текущего checkout/config, это должно быть заметно.

### Файлы

- `src/memco/local_artifacts.py` или соответствующий artifact builder
- `src/memco/release_check.py`
- `tests/test_local_artifacts.py`

### Acceptance criteria

- нельзя спутать “historical green artifact” с “current release status”

### Запрещенные shortcuts

- просто дописать markdown snapshot
- не маркировать source of truth

---

## Шаг 5 — Жестко определить ingest contract

### Цель

Перед релизом надо убрать неясность: какие source types продукт реально поддерживает и как он ведет себя на unsupported inputs.

### Что сделать

1. Выбрать policy:

#### Либо strict mode

- unsupported `source_type` -> hard fail

#### Либо dual mode

- `strict_ingest_contract=true` -> hard fail
- dev mode -> permissive fallback

2. Если остается permissive path, он должен:
   - быть явно маркирован
   - не называться полным support
3. Проверить, что release/runtime mode использует именно нужную политику.

### Файлы

- `src/memco/services/ingest_service.py`
- возможно `src/memco/config.py`
- `tests/test_ingest_service.py`

### Acceptance criteria

- список поддерживаемых source types соответствует реальному runtime behavior
- release-mode ingestion не ведет себя “магически”

### Запрещенные shortcuts

- оставить permissive fallback и в то же время писать, что source type строго валидируется

---

## Шаг 6 — Усилить operator-readiness набор до реального release bar

### Цель

Сейчас появился `operator_readiness_scope`, но он еще маловат как финальный барьер для релиза.

### Что сделать

1. Не удаляя synthetic benchmark, усилить operator-readiness cases:
   - multi-person isolation
   - unsupported premise
   - contradicted premise
   - current fact retrieval
   - temporal “when”
   - pending-review exclusion
   - evidence id presence
2. Сделать operator-readiness обязательным для release-grade gate.
3. Отдельно хранить:
   - pass rate
   - case list
   - failure list

### Файлы

- `src/memco/services/eval_service.py`
- `src/memco/release_check.py`
- `tests/test_eval_harness.py`
- `tests/test_release_check.py`

### Acceptance criteria

- release-grade gate не может быть зеленым, если operator-readiness не green
- operator-readiness не смешивается с generic synthetic benchmark

### Запрещенные shortcuts

- поднимать green только на synthetic benchmark

---

## Шаг 7 — Финально закрепить release scope в коде и артефактах

### Цель

После технических правок нельзя оставить маркетингово завышенную трактовку продукта.

### Что сделать

1. Зафиксировать scope продукта как:
   - local
   - private
   - operator-controlled
   - review-gated memory lifecycle
2. Не использовать release wording, которое обещает больше:
   - universal memory substrate
   - fully autonomous production memory without review caveat
3. Если есть docs/artifacts/CLI output, где релиз трактуется слишком широко — сузить формулировки.

### Файлы

- только после закрытия технических шагов:
  - `README.md`
  - relevant docs/artifacts generators
  - `tests/test_docs_contract.py`

### Acceptance criteria

- wording совпадает с реальным technical scope

### Запрещенные shortcuts

- менять только wording до технического закрытия шагов 1–6

---

## Шаг 8 — Финальный release proof, который нельзя подделать словами

### Цель

Сделать один финальный прогоn, после которого можно честно сказать “готово”.

### Обязательный набор

1. Full test suite
2. Release-grade gate
3. Live operator smoke
4. Fresh artifacts from current checkout
5. Health snapshot from same runtime

### Обязательные команды

```bash
env PYTHONPATH=/Users/martin/memco/src /Users/martin/memco/.venv/bin/python -m pytest -q
```

```bash
env PYTHONPATH=/Users/martin/memco/src /Users/martin/memco/.venv/bin/python -m memco.release_check
```

```bash
# сюда должен прийти новый release-grade gate, а не старый shortcut path
```

### Обязательные артефакты

- fresh release artifact
- fresh strict/release-grade artifact
- fresh live smoke artifact
- fresh benchmark/operator-readiness artifact
- fresh repo-local status snapshot

### Что считается достаточным доказательством

- текущий runtime green
- live smoke прошел на реальном provider path
- current artifacts свежие
- нет расхождения между текущим config status и release claim

### Что не считается достаточным доказательством

- старые `var/reports`
- только `pytest`
- только synthetic benchmark
- только docs snapshot

---

# Порядок выполнения без права менять местами

1. Шаг 0 — baseline
2. Шаг 1 — отделить checkout status от operator-configured status
3. Шаг 2 — сделать live smoke обязательным для release claim
4. Шаг 3 — сделать operator path воспроизводимым
5. Шаг 4 — ужесточить semantics артефактов
6. Шаг 5 — закрыть ingest contract ambiguity
7. Шаг 6 — усилить operator-readiness как release bar
8. Шаг 7 — только потом править wording/docs
9. Шаг 8 — финальный release proof

Если агент меняет порядок — он почти наверняка начнет закрывать symptoms вместо root cause.

---

# Стоп-условия

Агент обязан остановиться и не заявлять “готово”, если выполнено хотя бы одно из условий:

1. `release_eligible` все еще `False`
2. live smoke не запускался в release-grade path
3. green есть только в старых `var/reports`
4. release claim опирается на env, но это не отражено явно в артефактах
5. full suite не прогнана после финальных изменений
6. operator-readiness не green

---

# Definition of Done

Задача считается реально закрытой только если одновременно выполнено все ниже:

1. Текущий checkout имеет однозначный статус:
   - red without live credentials
   - green with valid operator runtime
   - и эта разница явно отражена в коде/артефактах
2. Release-grade gate не green без live smoke.
3. Live smoke выполняется на реальном provider path и реальном Postgres path.
4. Артефакты не маскируют исторический green под текущую готовность.
5. Ingest contract в release mode ведет себя строго и предсказуемо.
6. Operator-readiness обязателен для release claim.
7. Release wording соответствует реальному scope.
8. Full suite green после всех изменений.

---

# Короткая инструкция агенту-программисту

Если хочешь не срезать углы, действуй так:

1. сначала докажи текущую правду
2. потом закрой ambiguity runtime/release semantics
3. потом сделай live smoke обязательным
4. потом добей operator reproducibility
5. потом усили quality bar
6. только в самом конце разрешай себе писать “готово к релизу”

Любой другой порядок почти гарантированно приводит к ложному green.
