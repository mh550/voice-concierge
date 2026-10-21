"""The store's DDL (spec §4.2, B7, B9; plan C2 "Schema"), IF NOT EXISTS so two processes can open one file.

Times are INTEGER ms since the Unix epoch (UTC); `idle_ttl_s` is seconds. Thread ids are uuid4 hex and fact ids
AUTOINCREMENT, so nothing is reused after an erasure.
"""

from __future__ import annotations

SCHEMA_VERSION = 3
# V2-03: one row per visit, the episodes of concierge.memory v2 (plan 2026-10-21-V2 "The visit_summaries migration")
_VISIT_SUMMARIES = """CREATE TABLE IF NOT EXISTS visit_summaries (
  thread_id  TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  visit      INTEGER NOT NULL,                     -- threads.attributes.visits when the session started
  started_at INTEGER NOT NULL,                     -- ms
  ended_at   INTEGER,                              -- ms; NULL until the session's summary step
  summary    TEXT,                                 -- NULL until then, and when the summary failed or was skipped
  UNIQUE (thread_id, visit)
);"""
# What brings a file at version n - 1 up to n (the DDL below is already the newest, for a new file).
MIGRATIONS: dict[int, str] = {
    2: "ALTER TABLE anonymous_turn_metrics ADD COLUMN created_at INTEGER NOT NULL DEFAULT 0",  # C6-03
    3: _VISIT_SUMMARIES,  # V2-03; the UNIQUE constraint is its index
}

TABLES: tuple[str, ...] = (
    "threads",
    "state",
    "facts",
    "journal",
    "anonymous_turn_metrics",
    "daily_session_counts",
    "messages_for_michael",
    "visit_summaries",
)

# Per connection. journal_mode=WAL persists in the file; secure_delete zeroes freed content (erasure needs it);
# journal_size_limit=0 truncates the WAL after any checkpoint so old frames don't linger.
PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA secure_delete=ON",
    "PRAGMA journal_size_limit=0",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id             TEXT PRIMARY KEY,                 -- uuid4 hex, never reused (see "Ids")
  visitor_id     TEXT NOT NULL UNIQUE,             -- the scope: one thread per visitor (B2)
  created_at     INTEGER NOT NULL,                 -- ms
  last_active_at INTEGER NOT NULL,                 -- ms; set by get_or_create_thread
  idle_ttl_s     INTEGER NOT NULL DEFAULT 2592000, -- 30 days (B6)
  attributes     TEXT NOT NULL DEFAULT '{"visits": 1}',  -- JSON: {"visits": int}
  version        INTEGER NOT NULL DEFAULT 0        -- the fence (§4.2)
);

CREATE TABLE IF NOT EXISTS state (
  thread_id  TEXT PRIMARY KEY REFERENCES threads(id) ON DELETE CASCADE,
  state      TEXT NOT NULL CHECK (length(CAST(state AS BLOB)) < 8192),  -- VisitorState JSON
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,  -- never reused (see "Ids")
  thread_id     TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  slot          TEXT NOT NULL,
  value         TEXT NOT NULL,
  confidence    REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  source        TEXT NOT NULL CHECK (source IN ('user_said', 'user_typed', 'user_asked_to_remember')),
  channel       TEXT NOT NULL CHECK (channel IN ('voice', 'text')),
  turn_id       TEXT NOT NULL,
  created_at    INTEGER NOT NULL,
  valid_from    INTEGER NOT NULL,
  valid_to      INTEGER,                            -- NULL while valid
  superseded_by INTEGER REFERENCES facts(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS facts_valid ON facts(thread_id, valid_to);

CREATE TABLE IF NOT EXISTS journal (               -- append-only
  id         INTEGER PRIMARY KEY,
  thread_id  TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  session_id TEXT NOT NULL,
  ts_ms      INTEGER NOT NULL,
  type       TEXT NOT NULL,                        -- JournalType Literal, checked in models.py
  payload    TEXT NOT NULL DEFAULT '{}'            -- JSON
);
CREATE INDEX IF NOT EXISTS journal_thread ON journal(thread_id, id);

CREATE TABLE IF NOT EXISTS anonymous_turn_metrics (  -- B9: no visitor id, no text, numbers only; survives erasure
  id                     INTEGER PRIMARY KEY,
  session_id             TEXT NOT NULL,            -- random uuid4 hex per session
  turn                   INTEGER NOT NULL,
  eou_ms                 REAL,
  stt_ms                 REAL,
  llm_ttft_ms            REAL,
  tts_ttfb_ms            REAL,
  total_ms               REAL,
  memory_on_turn_path_ms REAL,
  preload_ms             REAL,
  extraction_ms          REAL,
  prompt_tokens          INTEGER,
  cached_tokens          INTEGER,
  compacted              INTEGER NOT NULL DEFAULT 0 CHECK (compacted IN (0, 1)),
  created_at             INTEGER NOT NULL         -- ms, rounded down to the minute
);

CREATE TABLE IF NOT EXISTS daily_session_counts (  -- B7: survives erasure; kept 2 days
  key   TEXT PRIMARY KEY,                          -- sha256(visitor_id + day) hex
  day   TEXT NOT NULL,                             -- UTC YYYY-MM-DD
  count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages_for_michael (  -- §4.6, written in C8; created now so erasure covers it
  id         INTEGER PRIMARY KEY,
  thread_id  TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  text       TEXT NOT NULL,
  contact    TEXT,
  created_at INTEGER NOT NULL
);

""" + _VISIT_SUMMARIES + "\n"
