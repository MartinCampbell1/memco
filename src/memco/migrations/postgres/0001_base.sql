CREATE TABLE IF NOT EXISTS workspaces (
  id BIGSERIAL PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  source_path TEXT NOT NULL,
  source_type TEXT NOT NULL,
  origin_uri TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  sha256 TEXT NOT NULL,
  imported_at TEXT NOT NULL,
  parsed_text TEXT NOT NULL DEFAULT '',
  meta_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'ready',
  UNIQUE(workspace_id, source_path, sha256)
);

CREATE INDEX IF NOT EXISTS idx_sources_workspace_status_type_imported
  ON sources(workspace_id, status, source_type, imported_at DESC, id DESC);

CREATE OR REPLACE VIEW source_documents AS
SELECT
  id,
  workspace_id,
  source_path,
  source_type,
  origin_uri,
  title,
  sha256,
  imported_at,
  parsed_text,
  meta_json,
  status
FROM sources;

CREATE TABLE IF NOT EXISTS source_chunks (
  id BIGSERIAL PRIMARY KEY,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0,
  section_title TEXT NOT NULL DEFAULT '',
  locator_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_source_chunks_source
  ON source_chunks(source_id, chunk_index);

CREATE TABLE IF NOT EXISTS source_chunk_fts (
  rowid BIGINT PRIMARY KEY,
  text TEXT NOT NULL,
  section_title TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS persons (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  slug TEXT NOT NULL,
  display_name TEXT NOT NULL,
  person_type TEXT NOT NULL DEFAULT 'human',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(workspace_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_persons_workspace_status_updated
  ON persons(workspace_id, status, updated_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS person_aliases (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  person_id BIGINT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  alias_type TEXT NOT NULL DEFAULT 'name',
  normalized_alias TEXT NOT NULL,
  confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  source_id BIGINT REFERENCES sources(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  UNIQUE(workspace_id, normalized_alias, alias_type)
);

CREATE TABLE IF NOT EXISTS person_merges (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  from_person_id BIGINT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  to_person_id BIGINT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  conversation_uid TEXT NOT NULL DEFAULT 'main',
  title TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL DEFAULT '',
  ended_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source_id, conversation_uid)
);

CREATE INDEX IF NOT EXISTS idx_conversations_workspace_started
  ON conversations(workspace_id, started_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS sessions (
  id BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  session_index INTEGER NOT NULL,
  session_uid TEXT NOT NULL,
  started_at TEXT NOT NULL DEFAULT '',
  ended_at TEXT NOT NULL DEFAULT '',
  detection_method TEXT NOT NULL DEFAULT 'single',
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(conversation_id, session_index),
  UNIQUE(conversation_id, session_uid)
);

CREATE INDEX IF NOT EXISTS idx_sessions_conversation_order
  ON sessions(conversation_id, session_index);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  session_id BIGINT REFERENCES sessions(id) ON DELETE SET NULL,
  message_index INTEGER NOT NULL,
  role TEXT NOT NULL DEFAULT 'unknown',
  speaker_label TEXT NOT NULL DEFAULT '',
  speaker_key TEXT NOT NULL DEFAULT '',
  speaker_person_id BIGINT REFERENCES persons(id) ON DELETE SET NULL,
  occurred_at TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(conversation_id, message_index)
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_order
  ON conversation_messages(conversation_id, message_index);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_speaker_key
  ON conversation_messages(conversation_id, speaker_key);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_person
  ON conversation_messages(speaker_person_id);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_session
  ON conversation_messages(session_id, message_index);

CREATE TABLE IF NOT EXISTS conversation_chunks (
  id BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  session_id BIGINT REFERENCES sessions(id) ON DELETE SET NULL,
  chunk_index INTEGER NOT NULL,
  start_message_index INTEGER NOT NULL,
  end_message_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  token_count INTEGER NOT NULL DEFAULT 0,
  locator_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(conversation_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_conversation_chunks_order
  ON conversation_chunks(conversation_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_conversation_chunks_source
  ON conversation_chunks(source_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_conversation_chunks_session
  ON conversation_chunks(session_id, chunk_index);

CREATE TABLE IF NOT EXISTS conversation_chunk_fts (
  rowid BIGINT PRIMARY KEY,
  text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_segments (
  id BIGSERIAL PRIMARY KEY,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  segment_type TEXT NOT NULL,
  segment_index INTEGER NOT NULL,
  chunk_id BIGINT REFERENCES source_chunks(id) ON DELETE SET NULL,
  conversation_id BIGINT REFERENCES conversations(id) ON DELETE CASCADE,
  session_id BIGINT REFERENCES sessions(id) ON DELETE SET NULL,
  message_id BIGINT REFERENCES conversation_messages(id) ON DELETE CASCADE,
  text TEXT NOT NULL DEFAULT '',
  locator_json TEXT NOT NULL DEFAULT '{}',
  occurred_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(source_id, segment_type, segment_index)
);

CREATE INDEX IF NOT EXISTS idx_source_segments_source
  ON source_segments(source_id, segment_type, segment_index);

CREATE INDEX IF NOT EXISTS idx_source_segments_message
  ON source_segments(message_id);

CREATE INDEX IF NOT EXISTS idx_source_segments_chunk
  ON source_segments(chunk_id);

CREATE INDEX IF NOT EXISTS idx_source_segments_session
  ON source_segments(session_id);

CREATE TABLE IF NOT EXISTS conversation_speaker_map (
  id BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  speaker_key TEXT NOT NULL,
  raw_label TEXT NOT NULL DEFAULT '',
  person_id BIGINT REFERENCES persons(id) ON DELETE SET NULL,
  resolution_method TEXT NOT NULL DEFAULT 'unresolved',
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(conversation_id, speaker_key)
);

CREATE TABLE IF NOT EXISTS memory_facts (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  person_id BIGINT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  category TEXT NOT NULL,
  subcategory TEXT NOT NULL DEFAULT '',
  canonical_key TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active',
  sensitivity TEXT NOT NULL DEFAULT 'normal',
  visibility TEXT NOT NULL DEFAULT 'standard',
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
  source_kind TEXT NOT NULL DEFAULT 'explicit',
  observed_at TEXT NOT NULL,
  valid_from TEXT NOT NULL DEFAULT '',
  valid_to TEXT NOT NULL DEFAULT '',
  event_at TEXT NOT NULL DEFAULT '',
  supersedes_fact_id BIGINT REFERENCES memory_facts(id) ON DELETE SET NULL,
  superseded_by_fact_id BIGINT REFERENCES memory_facts(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_facts_person_domain
  ON memory_facts(workspace_id, person_id, domain, category, status, observed_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_facts_canonical
  ON memory_facts(workspace_id, person_id, canonical_key, status, observed_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS memory_evidence (
  id BIGSERIAL PRIMARY KEY,
  fact_id BIGINT NOT NULL REFERENCES memory_facts(id) ON DELETE CASCADE,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  chunk_id BIGINT REFERENCES source_chunks(id) ON DELETE SET NULL,
  source_segment_id BIGINT REFERENCES source_segments(id) ON DELETE SET NULL,
  session_id BIGINT REFERENCES sessions(id) ON DELETE SET NULL,
  quote_text TEXT NOT NULL DEFAULT '',
  locator_json TEXT NOT NULL DEFAULT '{}',
  support_type TEXT NOT NULL DEFAULT 'supports',
  source_confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS memory_operations (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  person_id BIGINT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  operation_type TEXT NOT NULL,
  target_fact_id BIGINT REFERENCES memory_facts(id) ON DELETE SET NULL,
  before_json TEXT NOT NULL DEFAULT '{}',
  after_json TEXT NOT NULL DEFAULT '{}',
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_candidates (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  person_id BIGINT REFERENCES persons(id) ON DELETE SET NULL,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  conversation_id BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
  session_id BIGINT REFERENCES sessions(id) ON DELETE SET NULL,
  chunk_kind TEXT NOT NULL DEFAULT 'conversation',
  chunk_id BIGINT,
  domain TEXT NOT NULL,
  category TEXT NOT NULL,
  subcategory TEXT NOT NULL DEFAULT '',
  canonical_key TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  summary TEXT NOT NULL DEFAULT '',
  confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
  candidate_status TEXT NOT NULL DEFAULT 'extracted_candidate',
  publish_target_fact_id BIGINT REFERENCES memory_facts(id) ON DELETE SET NULL,
  dedupe_key TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  extracted_at TEXT NOT NULL,
  reviewed_at TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fact_candidates_status_domain
  ON fact_candidates(workspace_id, person_id, candidate_status, domain, extracted_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_fact_candidates_dedupe
  ON fact_candidates(workspace_id, dedupe_key, candidate_status, extracted_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS review_queue (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  person_id BIGINT REFERENCES persons(id) ON DELETE SET NULL,
  candidate_id BIGINT REFERENCES fact_candidates(id) ON DELETE SET NULL,
  candidate_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  resolved_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS retrieval_logs (
  id BIGSERIAL PRIMARY KEY,
  workspace_id BIGINT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
  person_id BIGINT REFERENCES persons(id) ON DELETE SET NULL,
  route_name TEXT NOT NULL DEFAULT 'retrieve',
  query_hash TEXT NOT NULL,
  query_length INTEGER NOT NULL DEFAULT 0,
  domain_filter TEXT NOT NULL DEFAULT '',
  fact_hit_count INTEGER NOT NULL DEFAULT 0,
  fallback_hit_count INTEGER NOT NULL DEFAULT 0,
  unsupported_premise_detected INTEGER NOT NULL DEFAULT 0,
  fact_ids_json TEXT NOT NULL DEFAULT '[]',
  fallback_refs_json TEXT NOT NULL DEFAULT '[]',
  latency_ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrieval_logs_workspace_created
  ON retrieval_logs(workspace_id, created_at DESC, id DESC);
