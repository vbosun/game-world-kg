CREATE TABLE IF NOT EXISTS worlds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    runtime_mode TEXT NOT NULL DEFAULT 'legacy_demo',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    player_input TEXT,
    narration TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    turn_id TEXT,
    turn_index INTEGER NOT NULL,
    event_order INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    actor_id TEXT,
    participants_json TEXT NOT NULL DEFAULT '[]',
    payload_json TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    causal_parents_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS state_deltas (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    attr TEXT NOT NULL,
    old_value_json TEXT,
    new_value_json TEXT,
    delta_json TEXT,
    scope TEXT NOT NULL DEFAULT 'canonical'
);

CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    name TEXT,
    properties_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'canonical',
    valid_from_turn INTEGER NOT NULL,
    valid_to_turn INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_event_id TEXT,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    src_id TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    properties_json TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'canonical',
    valid_from_turn INTEGER NOT NULL,
    valid_to_turn INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    source_event_id TEXT,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS states (
    world_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    attr TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_turn INTEGER NOT NULL,
    scope TEXT NOT NULL DEFAULT 'canonical',
    source_event_id TEXT,
    PRIMARY KEY (world_id, entity_id, attr, scope)
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    source_event_id TEXT,
    memory_text TEXT NOT NULL,
    truth_scope TEXT NOT NULL,
    scope_key TEXT NOT NULL DEFAULT '',
    layer TEXT NOT NULL DEFAULT 'episodic',
    memory_kind TEXT NOT NULL DEFAULT 'generic',
    valid_from_turn INTEGER,
    valid_to_turn INTEGER,
    supersedes_memory_id TEXT,
    merged_from_json TEXT NOT NULL DEFAULT '[]',
    salience REAL NOT NULL DEFAULT 0.5,
    valence REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 1.0,
    last_recalled_turn INTEGER,
    evidence_refs_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS conversation_segments (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    source_event_id TEXT,
    speaker_id TEXT,
    segment_index INTEGER NOT NULL,
    segment_kind TEXT NOT NULL DEFAULT 'dialogue',
    text TEXT NOT NULL,
    span_start INTEGER NOT NULL DEFAULT 0,
    span_end INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_ops (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_event_id TEXT NOT NULL,
    segment_id TEXT,
    op_type TEXT NOT NULL,
    layer TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    memory_text TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'candidate',
    applied_event_id TEXT,
    reason TEXT,
    created_at TEXT NOT NULL,
    applied_at TEXT
);

CREATE TABLE IF NOT EXISTS review_queue (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_event_id TEXT,
    memory_op_id TEXT,
    reason TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS source_texts (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    text TEXT NOT NULL,
    turn_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_refs (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    span_start INTEGER,
    span_end INTEGER,
    text TEXT,
    extractor TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extraction_candidates (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    candidate_json TEXT NOT NULL,
    scope TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'candidate',
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE TABLE IF NOT EXISTS projection_status (
    world_id TEXT NOT NULL,
    projector TEXT NOT NULL,
    projected_turn INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (world_id, projector)
);

CREATE TABLE IF NOT EXISTS action_templates (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    label TEXT NOT NULL,
    target_id TEXT,
    target_selector_json TEXT NOT NULL DEFAULT '{}',
    arg_schema_json TEXT NOT NULL DEFAULT '{}',
    risk TEXT NOT NULL DEFAULT 'low',
    reason TEXT NOT NULL DEFAULT '',
    preconditions_json TEXT NOT NULL DEFAULT '[]',
    effects_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(world_id, action_id)
);

CREATE TABLE IF NOT EXISTS world_specs (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    validation_report_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bootstrap_runs (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL,
    world_spec_id TEXT NOT NULL,
    spec_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    event_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(world_id, spec_hash, status)
);

CREATE INDEX IF NOT EXISTS idx_events_world_turn ON events(world_id, turn_index, event_order);
CREATE INDEX IF NOT EXISTS idx_states_world_entity ON states(world_id, entity_id);
CREATE INDEX IF NOT EXISTS idx_edges_world_src ON edges(world_id, src_id, valid_to_turn);
CREATE INDEX IF NOT EXISTS idx_memories_world_owner ON memories(world_id, owner_id);
CREATE INDEX IF NOT EXISTS idx_conversation_segments_turn ON conversation_segments(world_id, turn_id, segment_index);
CREATE INDEX IF NOT EXISTS idx_memory_ops_source ON memory_ops(world_id, source_event_id, status);
CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(world_id, status);
CREATE INDEX IF NOT EXISTS idx_outbox_status_topic ON outbox(status, topic, created_at);
CREATE INDEX IF NOT EXISTS idx_source_texts_world ON source_texts(world_id, source_type);
CREATE INDEX IF NOT EXISTS idx_evidence_refs_world ON evidence_refs(world_id, source_id);
CREATE INDEX IF NOT EXISTS idx_action_templates_world ON action_templates(world_id, enabled);
CREATE INDEX IF NOT EXISTS idx_world_specs_world ON world_specs(world_id, spec_hash);
CREATE INDEX IF NOT EXISTS idx_bootstrap_runs_world ON bootstrap_runs(world_id, spec_hash);
