Я бы сказал так:

как master spec / архитектурный документ — очень норм
как прямой промпт для автономного programmer-agent’а — слегка перегружено и местами слишком широко по scope
По ощущениям это уже не просто ТЗ, а spec + architecture doc + roadmap + eval plan + prompt appendix в одном файле. Это скорее плюс, но есть нюанс.

Что в нём реально хорошо
1. Правильно поймано главное отличие от обычного RAG
Самые важные инварианты у тебя заданы правильно:

domain-structured memory
person-scoped memory
evidence-first
refusal on unsupported premise
Это хорошо видно в §3 и особенно в финальных инвариантах в §50 (No personal claim..., Every memory fact belongs..., Structured memory is the source of truth).

Это, честно, самая важная часть. Тут ТЗ не уезжает в «сделайте умный RAG».

2. Есть не только идея, но и операционализация
У тебя не абстрактное “реализовать память”, а уже:

pipeline (§7)
storage/data model (§10)
domain schemas (§12–18)
retrieval contract (§24)
answer/refusal policy (§25)
diff/update flow (§26)
API/CLI (§27–28)
evaluation harness (§29)
rollout phases (§35)
DoD (§47)
То есть инженер не останется в пустоте.

3. Хорошо, что psychometrics уже понижен в приоритете
Ты не заставляешь делать это в полном виде в P0:

в §6.4 psychometrics можно stub/partial
в §17 прямо расписано P0: stub, P1: Big Five + Values, P2: all 9
Это очень здравая декомпозиция.

4. Отличный акцент на evaluation
Большинство таких ТЗ разваливаются именно тут, а у тебя есть:

golden set
adversarial questions
baselines
judge protocol
error taxonomy
token/latency accounting
Это сильная часть документа.

Где я вижу главные риски
1. P0 всё ещё слишком жирный
Формально есть приоритеты, но фактически P0 включает очень много:

ingestion
speaker resolution
chunking
5 доменов
extraction orchestration
consolidation
retrieval
refusal
chat endpoint
API + CLI
eval
token/latency logging
Смотри §6.4, §35, §47.
Для “первой рабочей версии” это уже почти целая платформа.

Риск: агент начнёт параллельно строить infra, schemas, API, eval, parsers и в итоге не добьёт главное — качественный end-to-end vertical slice.

2. Смешаны два режима: prototype и production system
В начале ты пишешь “production-ready prototype”, а дальше документ реально включает:

tenant model (§10.1)
auth/authorization/security (§32)
observability (§33)
review queue (§40)
staging/prod readiness (§45)
production hardening phase (§35 Phase 11)
То есть документ одновременно про:

доказать идею persona-memory
построить production-ish service
Это не фатально, но для агентной реализации это опасно: агент может зарыться в Celery/Redis/Alembic/admin endpoints до того, как появится качественный memory loop.

3. Не до конца оформлен lifecycle: candidate facts vs active facts
У тебя это логически есть:

invalid -> reject / needs_review
active facts require evidence
staging/candidates упомянуты в Phase 4
Но в data model (§10) я вижу memory_facts, memory_evidence, memory_operations, но не вижу явно отделённого слоя candidate/staging facts как полноценного контракта.

Для такой системы это важно. Иначе размывается вопрос:

что уже считается truth-store,
что ещё только кандидат после extraction,
где проходит граница между validate/consolidate/review/publish.
Я бы это усилил.

4. API security model не до конца доведён до request contract
В §32 у тебя правильно сказано:

auth on all APIs
row-level authorization
sensitive visibility rules
Но в примерах API (POST /chat, retrieval/list/update) я вижу в основном tenant_id, person_id, message/options — но не вижу явного viewer/actor context:

кто спрашивает,
имеет ли он право видеть sensitive domains,
действует ли он от имени owner, admin, support, другого пользователя.
Если это multi-user/multi-tenant система, это надо сделать explicit, иначе security section остаётся правильной декларацией, но не контрактом.

5. Модель данных слишком “conversation-centric” для PDF/doc ingestion
Ты поддерживаешь PDF/email/plaintext/chat export в одном pipeline, но сущности в §4/§10 в основном заточены под:

conversation
session
turn
message
speaker
Для чатов и email-thread это ок.
Для произвольного PDF/документа — уже не так естественно.

Тут есть риск awkward-адаптации:

либо делать fake speaker/message structure,
либо ломать parser semantics.
Я бы либо:

ввёл более общий слой source_units / source_segments,
либо очень чётко описал, как non-conversational documents нормализуются в messages/turns.
6. Некоторые метрики выглядят как research aspirations, а не как жёсткие acceptance gates
Например в §6.2:

p50 <= 30ms
chat-time extra tokens <= 5.5k
retrieval availability 99.9%
accuracy 96–98%
Это хорошие ориентиры, но без:

фиксированного железа,
dataset shape,
corpus size,
model config,
deployment mode
они плохо работают как жёсткий KPI для implementer’а.

Я бы оставил их как:

target / stretch goal а вот acceptance для P0 сделал бы проще и бинарнее.
Что бы я поправил перед тем, как отдавать это “программисту-агенту”
Обязательно
1. Сделать отдельный Execution Brief
Сейчас файл почти 4k строк. Для человека это ок, для автономного агента — риск распыления.

Я бы оставил этот документ как SPEC_FULL.md, а рядом сделал бы EXECUTION_BRIEF.md на 1–2 страницы:

текущая цель: только P0a
in-scope прямо сейчас
out-of-scope прямо сейчас
какие 3 инварианта нельзя нарушать
какие e2e тесты должны пройти
какой вертикальный slice считать done
2. Разрезать P0 на P0a / P0b
Например:

P0a

JSON/plaintext ingestion
speaker resolution
chunking
3 домена: Biography, Preferences, Work
evidence storage
consolidation basic
retrieval
refusal
CLI + minimal API
1 golden eval set
P0b

Experiences, Social Circle
incremental update
rollback
better eval
more parsers
Так агенту будет легче реально дойти до результата.

3. Явно ввести state machine факта
Например:

extracted_candidate -> validated_candidate -> active | needs_review | rejected | superseded | deleted

И описать:

где какой статус возникает,
кто/что может переводить из одного в другой,
можно ли отвечать из candidate,
что логируется.
4. Явно добавить concurrency/update semantics
Нужны правила:

что если два build/update job идут одновременно по одному person_id
есть ли domain-level locking
optimistic version check или serial execution
что такое safe reprocessing
Idempotency у тебя есть (§43.3), но concurrency policy я бы ещё зафиксировал.

Что бы я упростил без сожаления
1. Tenancy/auth/admin — не в первый вертикальный slice
Если цель — доказать качество memory architecture, то:

tenants,
review admin,
dashboards,
full auth matrix
лучше отодвинуть до момента, когда core memory уже работает.

2. Psychometrics — держать выключенным по умолчанию
Даже если оставить schema, я бы в implementation brief написал:

default off
не влияет на factual answering
не блокирует MVP
Потому что этот домен даёт много safety/compliance шума при относительно небольшой ценности для первого релиза.

3. PDF ingestion — либо упрощённо, либо позже
Если нет жёсткого требования по PDF в MVP, я бы сделал:

P0: JSON/plaintext/chat transcript
P1: email/PDF/WhatsApp/Telegram
Иначе parser layer разрастается раньше core memory.

Что особенно удачно и я бы точно оставил
unified memory_facts + memory_evidence + memory_operations (§10.6–10.8)
Это хороший pragmatic tradeoff. Я бы не делил по отдельным таблицам на каждый домен в MVP.
planner schema (§24.2)
Очень полезно, что planner не “магический”, а должен вернуть structured retrieval plan.
refusal/unsupported premise logic (§24.6, §25)
Это один из самых ценных кусков ТЗ.
phases/backlog/DoD (§35–36, §47)
Это делает документ исполнимым, а не просто красивым.
Мой итоговый verdict
Да, ТЗ норм. Даже сильное.
Я бы оценил примерно так:

как архитектурный master doc: 9/10
как документ, который можно прямо сейчас скормить coding agent’у без дополнительной рамки: 7/10
Почему не 10/10
Не из-за слабой архитектуры, а из-за того, что документ:

слишком монолитный,
местами смешивает prototype и production,
и ещё не до конца зажимает implementer’a в один конкретный vertical slice.
Если совсем практично: отправлять так или править?
Человеку-сеньору — уже можно отправлять почти как есть.
Автономному агенту — я бы сначала сделал короткий execution brief и урезал P0.

Если хочешь, я могу следующим сообщением сделать одно из двух:

жёсткий redline review этого ТЗ
— список конкретных правок “заменить/вынести/сократить”;
сжать его в agent-executable v2
— короткую версию на 1–2 страницы, которую уже безопасно отдавать программисту-агенту.
Вы
09:09
агент не дурак, он сам как сеньер программист. а ты можешь пожалуйста глянуть мои проекты hermesmemory и memograph(mymacagent) там как будто бы уже есть часть которую можно повзаимствовать для новой системы

Вы
09:26
агент не дурак, он сам как сеньер программист. а ты можешь пожалуйста глянуть мои проекты hermesmemory и memograph(mymacagent) там как будто бы уже есть часть которую можно повзаимствовать для новой системы

Hermes
Hermes
09:26
Да, посмотрел: и KB, и живые репы /Users/martin/hermesmemory и /Users/martin/mymacagent.

Короткий вывод: да, там реально уже есть хороший задел, причём в двух разных плоскостях:

HermesMemory — это уже почти готовый backend/substrate для новой memory-системы: ingestion, source registry, chunking, FTS, claims + provenance, compile jobs, KB API.
Memograph / MyMacAgent — это сильный upstream intelligence layer: local capture, normalization, entity extraction, graph shaping, review/apply loop, alias/merge overlays.
Если совсем практично:

Базу новой системы я бы строил скорее поверх HermesMemory,
а из Memograph портировал бы normalization + review/consolidation + live-capture bridge.

Что уже есть в hermesmemory и очень стоит повзаимствовать
Я смотрел в первую очередь:

src/hermes_memory/schema.sql
src/hermes_memory/importers.py
src/hermes_memory/compile.py
src/hermes_memory/claims.py
src/hermes_memory/storage.py
src/hermes_memory/query.py
src/hermes_memory/api.py
src/hermes_memory/memograph.py
1. Очень хороший evidence/source layer
В schema.sql уже есть нужный фундамент:

sources
source_chunks
source_chunk_fts
claims
claim_provenance
pages
links
jobs
lint_findings
output_artifacts
Самое ценное тут — claim_provenance:

claim_id
source_id
chunk_id
quote_text
locator_json
support_type
Для новой persona-memory это прям золото.
В твоём новом дизайне это почти без изменений превращается в:

fact_evidence
candidate_evidence
support / contradict / mentions / weak_signal
2. Ingestion уже почти готов
importers.py уже умеет нормальный intake для:

md/txt/json/jsonl/html
pdf/docx
csv/tsv
папок документов
AI chats
telegram
repo imports
hermes sessions
obsidian sync
То есть новый проект не надо заново начинать с file ingestion.
Это уже решено на достаточно хорошем уровне.

3. Compile contract surprisingly close к твоему новому ТЗ
В compile.py уже есть очень правильная мысль:

есть CompilePlan
есть LLMCompilePlan
есть deterministic / llm / hybrid strategy
LLM просят:
использовать только supported info,
сохранять contradictions,
давать quote_text,
работать по structured JSON contract,
потом output санитизируется и fallback’ится на deterministic seed
Это очень близко к твоей идее evidence-first extraction.

Особенно важен вот этот паттерн:

deterministic seed
LLM enhancement
sanitize LLM plan
fallback если LLM повёл себя плохо
Для нового typed-memory пайплайна это, по сути, можно оставить как архитектурный шаблон.

4. Conflict semantics уже есть
В claims.py уже есть полезные статусы:

duplicate_support
coexists_contextual
superseded_temporal
unresolved_conflict
Это не полная state machine для нового persona-memory, но очень хороший starting point.
Я бы это не выбрасывал, а расширил до более явного lifecycle.

5. Query/search слой уже пригодный
storage.py + query.py уже дают:

FTS по pages / claims / source chunks
get_page_detail
get_claim_detail
compact query context
citations/provenance
knowledgebase action surface
Это не field-level planner из paper, но как fallback retrieval over evidence/raw sources — отлично.

6. Уже есть мост к Memograph
Это вообще важный момент: в src/hermes_memory/memograph.py уже есть read-only bridge к базе Memograph, который нормализует сессии и тащит их в HermesMemory-подобную форму.

То есть интеграция между этими двумя мирами у тебя уже не с нуля.

Что в hermesmemory я бы не брал как source of truth без изменений
1. Page-centric модель
Сейчас truth layer там всё ещё во многом крутится вокруг:

pages
compiled_truth_md
summary_md
timeline_md
Для нового persona-memory это уже слишком wiki-centric.

То есть:

как materialization/export layer — да
как primary truth store — нет
2. Нет явного person/domain/fact lifecycle
Сейчас claims generic:

subject
predicate
object_value
qualifiers/time/conflict/provenance
Но нет явных вещей типа:

person_id
domain
fact_status
candidate vs active
superseded_by
review_required
visibility_policy
Это и будет новый слой, который надо добавить.

Что уже есть в memograph / mymacagent и что реально стоит вытащить
Я смотрел:

Sources/MyMacAgent/Database/Migrations/V005_KnowledgeGraph.swift
Knowledge/KnowledgePipeline.swift
Knowledge/ClaimExtractor.swift
Knowledge/EntityNormalizer.swift
Knowledge/KnowledgeCompiler.swift
Knowledge/KnowledgeMaintenance.swift
Data/SearchEngine.swift
Data/ContextSnapshotQueryPlanner.swift
Database/Migrations/V015_ContextSnapshotSearchFTS.swift
Fusion/ContextFusionEngine.swift
плюс модели KnowledgeMergeOverlayRecord, KnowledgeReviewDecisionRecord, KnowledgeAliasOverrideRecord
1. Лучшее, что там есть — normalization/consolidation/review loop
Вот это реально сильная часть.

Есть:

EntityNormalizer
alias overrides
merge overlays
review decisions
applied actions
maintenance artifacts / review drafts / apply-ready drafts
То есть там уже есть не просто extraction, а операционная петля по улучшению knowledge layer:

найти мусор/дубли/weak topics
предложить merge/reclassify/suppress
применить safe actions
перестроить materialized notes
Это очень близко к тому, что новой системе нужно для:

consolidation,
human review,
alias resolution,
merge semantics.
Если совсем честно, вот эту часть я бы точно переиспользовал концептуально.

2. Есть knowledge graph layer
V005_KnowledgeGraph.swift создаёт:

knowledge_entities
knowledge_claims
knowledge_edges
Это полезный промежуточный abstraction layer.

Плюсы:

уже есть entity types:
project
tool
model
topic
site
person
issue
lesson
есть стабильные id
есть edges с weight и supporting claim ids
Для нового проекта это не финальная схема, но как inspiration/useful module — да.

3. Incremental materialization там продумана лучше, чем обычно
KnowledgePipeline.swift / KnowledgeCompiler.swift умеют:

upsert entities
upsert claims
upsert edges
materialize only impacted notes
учитывать connected entities
работать с suppression / overlays
То есть у тебя уже есть хорошая практика:

не пересобирать всё тупо целиком, а делать incremental compile/materialization.

Это очень пригодится для новой системы.

4. Search over canonicalized context snapshots — тоже очень полезен
SearchEngine.swift + ContextSnapshotQueryPlanner.swift + V015_ContextSnapshotSearchFTS.swift — это хороший кусок.

Особенно полезные идеи:

FTS не по сырым несвязанным данным, а по resolved/canonical тексту
поддержка linked contexts через canonical_context_id
fallback FTS -> LIKE
аккуратный planner, который знает, как собирать select/from для разных schema versions
Если в новой системе будет live capture / transcript evidence, этот кусок очень полезен.

5. ContextFusionEngine.swift — хороший ingestion primitive
AX + OCR fusion там сделан довольно прагматично:

выбирается ax, ocr, ax+ocr, none
пишется merged text
считается hash
сохраняются source ids
Это отличный primitive для raw evidence ingestion, если новая система тоже захочет on-device capture.

Что в memograph я бы не переносил как есть
1. Heuristic extractor не должен стать сердцем новой системы
ClaimExtractor.swift сейчас строит knowledge в основном из:

daily summaries
session data
эвристик по темам/тулзам/relations
Для persona-memory нового класса это маловато:

слишком summary-centric
слабая granular provenance
нет fact candidate state
нет strong domain schemas
То есть:

как bootstrap heuristic layer — ок
как основная extraction architecture — нет
2. knowledge_claims там слабее по evidence, чем в hermesmemory
В Memograph claim хранит:

window start/end
summary date/generated_at
subject entity
predicate
object text
confidence
qualifiers
source kind
Но нет отдельной таблицы direct evidence вроде:

exact quote
source chunk id
locator
support type
То есть по части factual grounding HermesMemory сильнее.

3. Advisory/runtime/UI stuff mostly irrelevant
Большой кусок MyMacAgent — это:

advisory sidecar
account routing
provider runtime
macOS app plumbing
release/signing/notarization
Для нового typed-memory engine это почти всё лишнее.

Самый важный вывод
Если брать один проект за основу
Я бы выбрал:

hermesmemory как foundation
Потому что там уже есть:

source/evidence model
ingestion
chunking + FTS
claims + provenance
compile jobs
query/action API
Hermes-oriented KB surface
А из memograph я бы портировал лучшие идеи, а не runtime целиком:

EntityNormalizer
alias overrides
merge overlays
review decisions
maintenance/apply loop
canonical snapshot search patterns
context fusion, если нужен live capture
Как бы я это собрал в новую систему
Ядро новой системы
Добавил бы новый typed layer поверх/рядом с hermesmemory:

persons
fact_domains
fact_candidates
facts
fact_evidence
fact_operations
fact_review_decisions
alias_overrides
merge_overlays
Где что брать:
raw/evidence/storage/api → из hermesmemory
normalization/review/merge/apply → из memograph
new typed domain schemas + planner → писать заново
Что бы я делал первым делом
Phase 1
Из hermesmemory переиспользовать:

sources
source_chunks
source_chunk_fts
ingestion/importers
job queue
query fallback
knowledgebase API surface
Phase 2
Из memograph переиспользовать/портировать:

EntityNormalizer
KnowledgeAliasOverrideRecord
KnowledgeMergeOverlayRecord
KnowledgeReviewDecisionRecord
часть KnowledgeMaintenance логики
Phase 3
Написать новый typed compiler: вместо:

page_operations
claim_operations
link_operations
получить:

fact_candidate_operations
domain-specific typed payloads:
biography
preferences
relationships
work/projects
experiences
Phase 4
Оставить старый search как fallback:

typed facts first
raw source search second
pages/notes/graph third
Если совсем blunt verdict
Самое ценное в hermesmemory
claim_provenance
ingestion/importers
hybrid deterministic+LLM compile contract
FTS over raw/source/page/claim
Hermes KB action surface
Самое ценное в memograph
EntityNormalizer
merge/alias/review/apply loop
incremental materialization
canonical context search planner
AX+OCR fusion / local capture ingestion
Самое слабое место обоих относительно нового ТЗ
Оба проекта пока не имеют полноценного:

person_id-scoped typed fact store
candidate -> validated -> active -> superseded/rejected lifecycle
domain-aware retrieval planner
explicit viewer/security policy
direct structured persona domains as primary truth layer
Мой practical recommendation
Не пытаться “натянуть” новый persona-memory на текущие pages или на memograph knowledge_notes напрямую.
Это будет полумера.

Лучше так:

HermesMemory = evidence substrate + serving layer
Memograph = live capture + normalization + review/consolidation ideas
Новый модуль = typed persona memory core

Я посмотрел живые репы и ТЗ ещё раз. По моей оценке:

Очень грубо в процентах
Если считать весь проект целиком
то у нас уже есть примерно 55–60% заготовок.

Я даже посчитал себе грубую weighted-оценку по основным блокам — вышло 58.2% reusable foundation.

Но если считать только новое ядро именно Synthius-style persona memory
то готово скорее 20–25%.
У меня получилась более строгая оценка: 22.5%.

Почему две цифры
Потому что:

инфраструктура, ingestion, provenance, storage, query, normalization, review loops — у нас уже очень прилично есть;
а вот самое специфичное новое ядро ещё надо дописать:
typed persona domains,
person_id-scoped fact lifecycle,
CategoryRAG/planner,
refusal-on-absence,
diff/rollback именно для typed facts,
eval harness под это ТЗ.
То есть правда такая:

как инженерный фундамент — мы уже сильно не с нуля;
как готовый Synthius-Mem-аналог — ещё нет, там ядро надо строить.

Что я реально посмотрел
HermesMemory
Я проверил локальный код. После фильтрации build/venv/архивного мусора там примерно:

421 файлов
~62.6k строк текста
в schema.sql уже есть:
sources
source_chunks
source_chunk_fts
claims
claim_provenance
pages
jobs
И это очень сильная база.

Особенно ценно, что у тебя уже есть прямой substrate для:

ingestion источников,
chunking,
FTS,
claims,
provenance/evidence,
compile jobs.
Memograph / MyMacAgent
Тоже посмотрел локальный код. После фильтрации build/.venv там примерно:

384 файлов
~127.8k строк текста
И там уже есть:

KnowledgePipeline
EntityNormalizer
KnowledgeMaintenance
knowledge_entities
knowledge_claims
knowledge_edges
ContextSnapshotQueryPlanner
ContextFusionEngine
То есть очень сильный задел на:

normalization,
alias resolution,
consolidation/review,
graph shaping,
local capture / AX+OCR fusion,
incremental materialization.
Что уже есть почти готовое
1. Ingestion / source substrate
Тут у нас уже очень много.

Из HermesMemory:
importers
source registry
source chunks
FTS
evidence/provenance
Из Memograph:
контекстные снапшоты
AX/OCR fusion
session/context normalization
Моя оценка:
80–90% готовности как foundation.

2. Provenance / evidence-first design
Тоже уже очень хороший уровень.

В HermesMemory claim_provenance почти напрямую соответствует тому, что нужно новой системе:

source
chunk
quote
locator
support type
Моя оценка:
75–85% готовности.

3. Consolidation / normalization / merge-review
Это уже не ноль, и тут Memograph реально полезен.

Есть:

EntityNormalizer
alias overrides
merge overlays
review decisions
maintenance/apply loop
Моя оценка:
60–70% готовности.

4. Query/search/retrieval substrate
Есть хороший fallback-уровень, но не финальный CategoryRAG.

HermesMemory уже умеет search/query/KB-serving
Memograph уже имеет planner-like patterns для context snapshots
Моя оценка:
35–50% готовности.

Что ещё НЕ сделано и это главное
Вот здесь основная дыра.

1. Typed persona domains
Поиск по локальному коду не показал у тебя готового слоя типа:

Biography
Experiences
Preferences
Social Circle
Work
Psychometrics
То есть у тебя есть generic claims / graph / pages / notes,
но нет ещё доменно-типизированного persona memory core.

Это примерно:
15–25% готовности.

2. Person-scoped fact lifecycle
Нет ещё явного ядра вида:

person_id
domain
fact_status
candidate -> active -> superseded/rejected
answerable / not-answerable
versioned typed updates
Это одна из самых важных недостающих частей.

Это примерно:
10–20% готовности.

3. Planner + refusal logic под это ТЗ
То есть не просто “найди похожее”, а:

выбери домены,
достань structured fields,
если нет attested facts — откажись.
Это у тебя пока скорее идея и частичные паттерны, чем готовый subsystem.

Это примерно:
25–35% готовности.

4. Eval harness под memory-spec
LoCoMo-style / adversarial / refusal / token accounting / latency —
это ещё надо собирать отдельно.

Это примерно:
15–25% готовности.

Мой честный вердикт
Если совсем по-простому
не с нуля вообще
примерно половина инженерной работы уже облегчена
но ключевая “новая магия” ещё не написана
То есть я бы сказал так:

Инженерно у нас уже есть ~55–60% основы.
Концептуально именно под новое ТЗ — скорее ~20–25% ядра уже есть.
В реальном effort это, наверное, экономит где-то 40–60% времени по сравнению с полным greenfield.

Какие external repo / open-source куски реально стоит заимствовать
Я ещё живо проверил несколько GitHub-реп через API.

Мои top picks
Для прямого использования или лёгкой интеграции
1. 567-labs/instructor
MIT
~12.8k stars
structured outputs for LLMs
Зачем:
это лучший кандидат для typed extraction в Pydantic/JSON schemas.

Я бы реально брал.

2. moj-analytical-services/splink
MIT
~2.1k stars
probabilistic data linkage
Зачем:
для:

dedupe,
entity matching,
merge candidate scoring,
review queue ranking.
Очень хороший кандидат, если хочешь не писать reconciliation heuristics полностью самому.

3. asg017/sqlite-vec
Apache-2.0
~7.5k stars
Зачем:
если захочешь локальный embedded vector/hybrid layer рядом с SQLite, а не отдельный сервис.

Не must-have, но полезно.

4. promptfoo/promptfoo
MIT
~20.3k stars
Зачем:
для:

adversarial eval,
refusal tests,
regression suites,
CI для memory QA.
Я бы почти точно брал для eval-пайплайна.

5. vibrantlabsai/ragas
Apache-2.0
~13.5k stars
Зачем:
для groundedness/faithfulness/context metrics.

Хорошо как eval helper, но не как core.

Скорее как inspiration / partial borrow, не как runtime dependency
6. mem0ai/mem0
Apache-2.0
~53.6k stars
Полезно для:

memory CRUD/update policy
add/update/delete/no-op logic
memory namespace patterns
Я бы не тащил целиком,
но точно бы посмотрел их updater semantics.

7. letta-ai/letta
Apache-2.0
~22.2k stars
Полезно для:

tiered memory model
agent-facing memory abstractions
Скорее архитектурное вдохновение, чем dependency.

8. getzep/graphiti
Apache-2.0
~25.2k stars
Полезно для:

temporal knowledge graph
provenance-aware graph memory
relationship updates over time
Очень ценный референс.
Но я бы скорее заимствовал идеи/схему, чем весь стек.

9. OpenRefine/OpenRefine
BSD-3-Clause
~11.8k stars
Полезно для:

clustering
merge review UX
reconciliation workflows
reversible operations thinking
Не для прямого embed, а для того, как делать human review / merge UI и workflow.

10. opensanctions/nomenklatura
MIT
~239 stars
11. alephdata/followthemoney
MIT
~268 stars
Полезно для:

entity schema
reconciliation model
provenance-rich entity integration
Очень хорошие “умные маленькие кирпичи”, особенно если захочешь сделать хорошую entity layer.

Что я бы собирал как “умного Франкенштейна”
Базовый рецепт
Основа:
HermesMemory как главный substrate
Портировать из Memograph:
EntityNormalizer
alias overrides
merge overlays
review decisions
maintenance/apply loop
ContextFusion ideas при необходимости
Взять извне:
Instructor — structured extraction
Splink — dedupe / record linkage
promptfoo + ragas — eval
sqlite-vec — только если нужен local hybrid retrieval
идеи из Graphiti / Mem0 / Letta, но не весь runtime
Что я бы НЕ делал
Я бы не строил это как чудовище из полноценных чужих фреймворков.

То есть я бы не делал:

HermesMemory + Letta runtime + Mem0 runtime + Graphiti runtime + ещё что-то сверху.
Это будет очень тяжёлый Frankenstein.

Лучше так:
свой core
свои таблицы
свои domain schemas
а извне брать узкие кирпичи, не “целые религии”
Мой practical recommendation
Лучший путь
Repo foundation:
новый модуль поверх HermesMemory

Что переносить:
из Memograph переносить consolidation intelligence, а не весь app/runtime.

Новые обязательные модули:
persons
fact_domains
fact_candidates
facts
fact_evidence
fact_operations
fact_review_decisions
Bottom line
Мой итог такой:

Да, у нас уже есть очень серьёзные заготовки.
Не greenfield.

Если грубо:

55–60% foundation уже есть
20–25% специфического Synthius-style core уже есть
40–60% общего effort можно сэкономить, если строить умно
И да — собирать это как аккуратного Франкенштейна вполне разумно,
но я бы делал Frankenstein из маленьких библиотечных кусков, а не из нескольких полноценных memory frameworks целиком.

Да. Я бы закрыл эти вопросы жёстко и без дальнейшего размывания scope примерно так.

Мой recommended decision pack для исполнителя
1) Финальный стек
Решение:

Язык/ядро: Python 3.11+
API: FastAPI
Схемы: Pydantic v2
Доступ к БД: SQLAlchemy 2.x
Хранилище для P0: SQLite/FTS5 + JSON, чтобы максимально переиспользовать HermesMemory
Очереди/фоновые jobs в P0: без обязательного Redis/Celery; можно синхронно или через лёгкий job runner
CLI: Typer/Click или расширение текущего HermesMemory CLI
LLM adapter: provider-agnostic, но с OpenAI-compatible transport + mock/fixture provider
Repo strategy: строить поверх HermesMemory substrate, а не внутри Memograph runtime; из Memograph портировать отдельные алгоритмы/идеи
Почему так:

это даёт максимальный reuse из hermesmemory;
не тащит Swift/Memograph как runtime dependency;
не заставляет сейчас перепрыгивать в Postgres/Redis/Celery, пока мы даже не закрыли первый vertical slice.
Важно:

Postgres/Redis — не P0 requirement.
Если потом дойдём до P1 multi-tenant/prod-like режима — тогда уже можно мигрировать storage/job layer.
2) Какой первый vertical slice считаем done
Решение: первый vertical slice = узкий, но end-to-end.

Done = когда система умеет:

импортировать multi-session conversation в JSON/plaintext;
нормализовать сообщения и явно резолвить 2 участников;
делать chunking с сохранением speaker/timestamp/message linkage;
извлекать и консолидировать 3 домена:
Biography
Preferences
Social Circle
сохранять только person-scoped facts с evidence;
строить structured retrieval без raw full-context replay;
отвечать на supported questions и refuse на unsupported/false-premise;
проходить e2e-сценарии:
pets
move
social contamination
preference reversal
Что НЕ входит в первый slice:

Work
Experiences
PDF/email
psychometrics
полноценный diff/rollback
полноценная admin UI
Почему именно так: этот slice уже доказывает:

person separation,
temporal update,
refusal,
evidence-first retrieval.
То есть он доказывает архитектуру, а не только ingestion.

3) Нужен ли Psychometrics в MVP
Решение:

Нет, не нужен в MVP как рабочий домен.
В P0 оставить только schema stub / enum compatibility stub.
Не извлекать, не использовать в retrieval, не использовать в answer generation.
По умолчанию disabled.
Итого:

psychometrics существует в модели мира,
но не является deliverable P0.
Это, кстати, хорошо бьётся с твоим же ТЗ: там psychometrics уже по сути сдвинут в later phase.

4) Обязательны ли PDF/email ingestion в первом релизе
Решение:

Нет.
P0 input formats:
JSON conversation
plaintext transcript with speaker labels
CSV/JSONL messages
PDF/email = P1
Что должно быть в P0:

parser interface и расширяемая ingestion architecture,
чтобы потом PDF/email добавлялись без переделки ядра.
5) Кто/что обрабатывает needs_review
Решение:

В P0 needs_review ставит система.
В P0 needs_review не попадает в normal retrieval/chat path.
В P0 его разбирает человек через:
минимальный admin endpoint/CLI,
или прямой review script,
без обязательной UI-панели.
Роли:

system → может ставить needs_review
owner/admin → может approve / reject / merge / supersede
Жёсткое правило:

ничего из needs_review не считается truth-source, пока не переведено в active.
То есть P0 не обязан иметь красивую review UI, но обязан иметь:

queue/list,
approve/reject path,
exclusion from active retrieval.
6) Какой actor/viewer security model нужен
Решение для P0: single-tenant personal system с заделом под multi-tenant.

Actor roles
system
owner
admin
eval
Viewer policy
owner: полный доступ к своим несекретным и секретным данным
admin: доступ только для review/maintenance paths, не для обычного chat path
system: внутренние операции build/retrieve/update
eval: только synthetic/test datasets
Sensitive facts
Для sensitive categories:

default visibility = private / restricted
в обычном chat path они доступны только owner-context
admin не должен видеть их “просто так” в обычном runtime, только через explicit review path
Tenant model
tenant_id хранить сразу
но в P0 деплой считаем single-tenant
полноценный multi-tenant ACL и org-sharing — не P0
7) Какие LLM-провайдеры и лимиты по cost/latency
Решение:

Providers
Обязательная поддержка:

OpenAI-compatible provider
mock provider
deterministic fixture provider для CI
Policy
Никакого auto-router в P0
Все модели должны быть pinned and explicit
Конфиг должен явно задавать:
EXTRACTION_MODEL
PLANNER_MODEL
ANSWER_MODEL
JUDGE_MODEL
Runtime recommendation
extraction/planner/repair: более дешёвая pinned structured-output capable модель
answer/judge: более сильная pinned модель
CI: только mock/fixture
Cost limits
Я бы поставил так:

абсолютный $ budget не является release gate для P0
но token accounting обязателен
и есть 2 жёстких бюджетных ограничения:
full-context path = запрещён в normal chat path
на fixture с длинной историей injected memory context должен быть <= ~6k extra tokens на запрос
То есть:

в P0 мы гейтим не “сколько долларов”, а
нераздувание prompt-а и
наличие отчёта по токенам.
Latency limits
В P0 hard gate я бы ставил только на retrieval layer:

CategoryRAG p50 <= 100ms
CategoryRAG p95 <= 250ms на фиксированном локальном fixture dataset.
Почему не на full /chat latency:
потому что provider network jitter и LLM latency слишком шумные для честного binary gate.

8) Acceptance criteria для P0 как бинарные gates
Вот это я бы сформулировал максимально жёстко, без research-theater.

P0 считается done только если одновременно выполнено всё ниже
A. Ingestion / normalization
импортируется multi-session conversation в JSON/plaintext
сохраняется порядок сообщений
speaker labels не теряются
unresolved speakers не назначаются молча
B. Person scoping
можно построить persona минимум для двух участников
facts одного участника не попадают другому
C. Core structured memory
реализованы и валидируются 5 core domains:
Biography
Experiences
Preferences
Social Circle
Work
psychometrics допускается только как stub, без реального query-time использования
D. Evidence rule
каждый active fact имеет evidence
fact без evidence не может стать active
E. Consolidation
duplicate facts merge-ятся
current-state facts могут supersede old state
historical facts не теряются
ambiguous/conflicting cases идут в needs_review
F. Retrieval
retrieval возвращает structured context
normal path не тащит full raw conversation
needs_review, rejected, deleted не попадают в normal retrieval
G. Answer safety
answer generator отвечает по supported facts
unsupported personal claims получают refusal / explicit “нет подтверждения”
adversarial suite проходит минимум 95/100
H. E2E scenarios
Обязательно проходят:

pets
move
social contamination
preference reversal
work skill
I. Tooling / interfaces
Есть:

API для build / retrieve / chat
CLI для build / inspect / review-basic
J. Tests / CI
unit + integration tests зелёные
CI проходит на mock/fixture provider
deterministic regression snapshots есть
K. Reports
Сгенерированы:

token report
latency report
golden/adversarial report
Коротко: что я бы ответил исполнителю прямо в 8 строк
Если совсем сжато, я бы зафиксировал так:

Стек: Python + FastAPI + Pydantic + SQLAlchemy, поверх HermesMemory substrate; P0 на SQLite/FTS5, без обязательного Postgres/Redis/Celery.
Первый vertical slice: JSON/plaintext → 2 speakers → chunking → Biography/Preferences/Social Circle → evidence-backed memory → retrieval → refusal → e2e pets/move/social contamination/preference reversal.
Psychometrics: не входит в MVP, только disabled stub.
PDF/email: не обязательны в первом релизе, это P1.
needs_review: ставит система; в P0 разбирает owner/admin через минимальный CLI/admin endpoint; needs_review не участвует в normal retrieval.
Security model: single-tenant personal by default, roles = system/owner/admin/eval, sensitive facts owner-only in normal chat path.
LLM policy: pinned OpenAI-compatible models + mock/fixture provider, no auto-router; hard cost gate нет, hard token gate есть.
P0 binary gates: import, person-scoping, 5 core domains + psych stub, evidence on all active facts, consolidation, structured retrieval, refusal, e2e tests, CI green, reports generated.