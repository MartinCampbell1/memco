 ТЗ на завершающую доработку Memco

   Status: historical remediation plan, not current release verdict.
   Current verdict lives in docs/2026-04-24_memco_release_closure.md and the active gate definition lives in docs/2026-04-21_memco_release_readiness_gate.md.
   Keep this file as historical implementation context; do not use it as fresh GO proof without rerunning the current gates.

   Цель

   Довести проект от состояния:

   •  repo-local GO
   •  почти всё закрыто

   до состояния:

   •  можно честно сказать, что замечания по качеству/надёжности закрыты
   •  оставшиеся риски не маскируются acceptance-only тестами
   •  runtime-путь реально соответствует заявленному контракту

   ──────────────────────────────────────────

   Границы этого ТЗ

   Входит

   Только то, что всё ещё не дотягивает после последнего большого коммита:

   1. live runtime всё ещё может работать через mock
   2. extraction архитектурно разнесён, но по сути остаётся rule/heuristic-heavy
   3. benchmark есть, но не является обязательным quality gate
   4. temporal answers ещё слишком грубые
   5. psychometrics всё ещё не дотягивает до “надёжного production-like optional module”
   6. Postgres-first оформлен контрактно, но не доведён до полноценного operational gate

   Не входит

   Этим ТЗ не надо заново открывать уже закрытые блоки:

   •  subject binding
   •  support level semantics
   •  pending-review exclusion
   •  RU/EN базовый support
   •  PDF/email ingestion
   •  answer contract с fact_ids / evidence_ids
   •  sessions / token chunking / overlap

   ──────────────────────────────────────────

   Шаг 1. Запретить `mock` как живой runtime по умолчанию

   Проблема

   Сейчас код контрактно объявляет openai-compatible default, но в живом checkout локальный settings.yaml всё ещё может поднимать
   MockLLMProvider.

   Это ломает claim:
    “LLM extraction is the default runtime path”

   Что нужно сделать

   1.1. Ужесточить runtime policy

   mock должен быть разрешён только в 3 режимах:

   •  unit/integration tests
   •  acceptance/benchmark fixture mode
   •  явный ручной opt-in для разработчика

   1.2. Добавить runtime guard

   Если root — это обычный repo-local runtime, а не test/eval temp root, и provider=mock, система должна:

   •  либо падать при инициализации extraction runtime
   •  либо явно маркировать runtime как fixture-only / non-production
   •  и release-check для обычного runtime не должен проходить как полноценный

   1.3. Разделить конфигурации

   Нужно явно развести:

   •  repo-local runtime config
   •  test/eval fixture config

   Чтобы fixture-path не маскировал живой runtime.

   Какие файлы затрагивать
   •  src/memco/config.py
   •  src/memco/llm.py
   •  src/memco/services/extraction_service.py
   •  src/memco/release_check.py
   •  при необходимости CLI/runtime health surface

   Acceptance criteria
   1. На обычном repo root ExtractionService.from_settings(...) не поднимает MockLLMProvider, если нет явного opt-in.
   2. mock в живом runtime либо запрещён, либо явно помечен как fixture-only и ломает полноценный gate.
   3. Отдельные eval/test roots по-прежнему могут использовать mock.
   4. Появляется отдельный тест на это поведение.

   ──────────────────────────────────────────

   Шаг 2. Перевести extraction в реально LLM-first режим

   Проблема

   Сейчас extraction структурно разнесён по доменам, но сами extractors в основном остаются regex/pattern-driven. Это хорошо как
   fallback/heuristics, но ещё не то, что должно быть основным runtime для full-quality memory.

   Что нужно сделать

   2.1. Ввести 2 разных режима extraction

   Основной режим
   •  LLM-first structured extraction
   •  по доменам
   •  со strict JSON schema
   •  с evidence/provenance/temporal fields

   Fallback режим
   •  rule-based / regex extractor
   •  только для:
     •  tests
     •  fixtures
     •  emergency fallback
   •  не должен быть основным production/runtime path

   2.2. Для каждого домена сделать domain prompt contract

   Минимум для:

   •  biography
   •  preferences
   •  social_circle
   •  work
   •  experiences
   •  psychometrics

   Каждый extractor должен иметь:

   •  domain instructions
   •  required fields
   •  ambiguity rules
   •  evidence requirements
   •  temporal handling rules
   •  negation handling

   2.3. Добавить live extraction regression suite

   Нужен набор non-trivial cases, где extraction проверяется не только на прямых фразах типа:
   •  I moved to Lisbon
   •  I like tea

   Но и на:
   •  косвенных формулировках
   •  отрицаниях
   •  self-corrections
   •  mixed-language snippets
   •  temporal phrases
   •  ambiguity

   2.4. Зафиксировать policy по negation/uncertainty

   Например:
   •  I don't like sushi не должен становиться positive preference
   •  I might move to Berlin не должен становиться current residence
   •  I used to work at X не должен становиться current employment

   Какие файлы затрагивать
   •  src/memco/services/extraction_service.py
   •  src/memco/extractors/base.py
   •  src/memco/extractors/*.py
   •  при необходимости отдельные prompt/schema helpers
   •  tests/test_extraction_contracts.py
   •  новые richer extraction tests

   Acceptance criteria
   1. Основной runtime extraction path использует LLM provider, а не regex-only logic.
   2. Rule-based extractor остаётся только fallback/fixture path.
   3. Для всех 5 core domains + psychometrics есть schema-backed extraction contract.
   4. Есть regression tests на:
     •  negation
     •  indirect phrasing
     •  temporal ambiguity
     •  RU/EN mixed-language snippets
   5. Published facts по-прежнему требуют evidence.

   ──────────────────────────────────────────

   Шаг 3. Сделать benchmark обязательным quality gate

   Проблема

   Сейчас benchmark появился в eval_service, но основной release-check всё ещё по сути опирается на:

   •  pytest gate
   •  acceptance artifact

   Этого недостаточно для честного quality claim.

   Что нужно сделать

   3.1. Разделить 2 уровня gate окончательно

   Acceptance gate
   •  быстрый
   •  deterministic
   •  CI-safe
   •  fixture oriented

   Benchmark gate
   •  отдельный обязательный шаг для quality claim
   •  не должен маскироваться acceptance artifact

   3.2. Встроить benchmark в release workflow

   Нужно сделать один из двух вариантов:

   Вариант A

   release-check всегда включает benchmark

   Вариант B

   Есть отдельный strict-release-check, который обязателен для claim “замечания закрыты полностью”

   3.3. Зафиксировать минимальные пороги

   Минимально:
   •  core_memory_accuracy >= 0.90
   •  adversarial_robustness >= 0.95
   •  person_isolation >= 0.99
   •  unsupported premise returning supported = 0
   •  positive answers with missing evidence ids = 0

   3.4. Артефакт должен быть отдельным

   Нужен отдельный machine-readable artifact:
   •  artifact_type = eval_benchmark_artifact
   •  с domain reports
   •  benchmark set reports
   •  token accounting by stage
   •  latency summary

   Какие файлы затрагивать
   •  src/memco/services/eval_service.py
   •  src/memco/release_check.py
   •  возможно src/memco/local_artifacts.py
   •  tests around release/benchmark contract

   Acceptance criteria
   1. Benchmark запускается отдельным обязательным quality path.
   2. Нельзя заявлять “всё закрыто”, если benchmark step не пройден.
   3. Отдельный benchmark artifact сохраняется и проверяется тестами.
   4. Acceptance и benchmark больше не смешиваются семантически.

   ──────────────────────────────────────────

   Шаг 4. Доработать temporal answer semantics

   Проблема

   Temporal model в storage/retrieval уже есть, но answer layer всё ещё слишком грубо отвечает на when-вопросы.

   Сейчас логика уровня:
   •  “It happened in X”

   недостаточна для корректной temporal semantics.

   Что нужно сделать

   4.1. Жёстко зафиксировать temporal precedence

   Для temporal answers использовать в таком порядке:

   1. event_at
   2. valid_from
   3. observed_at

   Но не как равнозначные поля — а с разной формулировкой ответа.

   4.2. Добавить разные answer templates

   Если есть `event_at`
   •  ответ как дата/время события

   Если нет `event_at`, но есть `valid_from`
   •  ответ как начало действия/состояния

   Если известен только `observed_at`
   •  ответ должен прямо говорить:
     •  “точная дата события неизвестна”
     •  “известно только, что это было сказано/зафиксировано тогда-то”

   4.3. Добавить contradiction/unknown temporal cases

   Например:
   •  вопрос про точную дату при наличии только observed timestamp
   •  вопрос “when” при current-state fact без event_at
   •  conflicting event dates

   Какие файлы затрагивать
   •  src/memco/services/answer_service.py
   •  src/memco/services/retrieval_service.py
   •  tests/test_answer_service.py
   •  tests/test_retrieval_service.py
   •  eval_service.py temporal benchmark cases

   Acceptance criteria
   1. when-answers не приравнивают observed_at к event_at.
   2. Есть явное различие в ответах для:
     •  event date known
     •  valid_from known
     •  only observed_at known
   3. Temporal cases покрыты тестами и benchmark cases.

   ──────────────────────────────────────────

   Шаг 5. Довести psychometrics до безопасного production-like optional режима

   Проблема

   Psychometrics больше не stub в старом виде, но всё ещё слишком rule-signal based для сильного claim “полноценный psychometric
   layer”.

   Что нужно сделать

   5.1. Разделить psychometrics на 2 слоя

   Слой A: evidence extraction
   •  извлечение psychometric signals
   •  evidence
   •  counterevidence
   •  confidence

   Слой B: trait scoring/update
   •  aggregation
   •  conservative update
   •  use_in_generation decision
   •  framework-specific thresholds

   5.2. Ужесточить `use_in_generation`

   По умолчанию use_in_generation должен быть False, если нет достаточных оснований.

   Минимум:
   •  либо несколько evidence items
   •  либо сильный explicit self-description
   •  и отсутствие существенного counterevidence

   5.3. Политика безопасности

   Psychometrics должно оставаться:
   •  non-factual
   •  non-diagnostic
   •  conservative
   •  неиспользуемым в retrieval как источник factual truth

   5.4. Ввести richer tests

   Нужны проверки на:
   •  conflicting signals
   •  low-confidence traits
   •  multiple frameworks in one snippet
   •  no factual leakage into answers

   Какие файлы затрагивать
   •  src/memco/extractors/psychometrics.py
   •  src/memco/services/retrieval_service.py
   •  src/memco/services/answer_service.py
   •  tests/test_style_psychometric_guardrails.py
   •  tests/test_extraction_contracts.py

   Acceptance criteria
   1. Psychometrics не участвует в factual retrieval.
   2. use_in_generation не выставляется агрессивно на слабых сигналах.
   3. Есть separation between extracted signal and scored profile.
   4. Counterevidence реально влияет на итог.

   ──────────────────────────────────────────

   Шаг 6. Довести Postgres-first contract до operational truth

   Проблема

   Сейчас Postgres-first оформлен как contract, но реальный основной gate живёт на sqlite fallback для temp eval roots.

   Это допустимо для локальной стабильности, но не закрывает вопрос:
    действительно ли canonical runtime уже operationally Postgres-first?

   Что нужно сделать

   6.1. Ввести отдельный full-claim gate на Postgres

   Нужен один официальный путь, который обязательно проходит на Postgres:

   •  schema init
   •  runtime bootstrap
   •  ingestion
   •  extraction
   •  retrieval
   •  release/baseline checks

   6.2. Не ломать локальный быстрый путь

   Быстрый sqlite-based local gate можно оставить, но он должен означать:
   •  quick local gate
   а не
   •  canonical full-quality gate

   6.3. Зафиксировать два уровня operational validation
   •  quick repo-local gate
   •  postgres canonical gate

   Какие файлы затрагивать
   •  src/memco/release_check.py
   •  src/memco/postgres_smoke.py
   •  src/memco/db.py
   •  возможно local_artifacts.py
   •  tests around postgres release path

   Acceptance criteria
   1. Есть отдельный стандартный gate, который проходит на Postgres.
   2. SQLite gate остаётся fallback/quick path.
   3. Full-quality claim не делается только на основании sqlite fallback run.

   ──────────────────────────────────────────

   Общий порядок выполнения

   Этап 1 — runtime integrity
   1. Шаг 1: запретить mock как живой runtime
   2. Шаг 6: оформить Postgres canonical gate

   Этап 2 — quality of extraction
   3. Шаг 2: сделать extraction реально LLM-first
   4. Шаг 5: усилить psychometrics

   Этап 3 — quality proof
   5. Шаг 4: доработать temporal answer semantics
   6. Шаг 3: встроить benchmark в обязательный gate

   ──────────────────────────────────────────

   Итоговый Definition of Done

   Можно считать этот хвост закрытым только если одновременно выполнено всё ниже:

   1. На живом repo-local runtime extraction не идёт через mock по умолчанию.
   2. Основной extraction path — LLM-first, а rule/regex path только fallback.
   3. release-check или отдельный strict gate включает benchmark artifact.
   4. Temporal answers различают event_at, valid_from, observed_at.
   5. Psychometrics остаётся safe/non-factual и более консервативно используется.
   6. Есть отдельный canonical Postgres validation path.
   7. Все новые tests зелёные.
   8. Ни один из этих пунктов не держится только на docs/contract wording без реального runtime proof.
