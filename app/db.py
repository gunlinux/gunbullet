"""Synchronous SQLite wiring for the demo app.

The hot read paths (``/users``, ``/users/<id>``) query a tiny table whose pages
live in the SQLite cache, so the SQL itself costs ~2 us. Routing that through
aiosqlite (a worker thread per connection) plus a connection pool added ~120 us
of plumbing per request and made concurrency *negative* under the GIL -- a 10x
throughput cliff for a 2 us read. So we use stdlib ``sqlite3`` directly and query
inline in the handler: no thread offload, no pool.

This is only safe because the queries are microseconds. A blocking call on the
event loop is fine at that scale; anything heavier or write-heavy should not use
this path.
"""

import sqlite3


def open_db(db_uri: str) -> sqlite3.Connection:
    # check_same_thread=False is defensive: Granian/uvicorn run one loop thread
    # per worker (separate workers are separate processes, each with its own
    # connection), and handlers never await between execute() and fetch*(), so
    # the shared connection is never used re-entrantly.
    conn = sqlite3.connect(db_uri, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_SEED_USERS = [
    ("loki", "loki@example.com", 37),
    ("alice", "alice@example.com", 29),
    ("bob", "bob@example.com", 42),
    ("carol", "carol@example.com", 35),
    ("dave", "dave@example.com", 51),
]


def init_db(conn: sqlite3.Connection) -> None:
    """Create the ``users`` table and seed it once, idempotently.

    Safe to run on every startup: the table is created if missing and seed rows
    are only inserted when the table is empty, so restarts don't duplicate data.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            age   INTEGER NOT NULL
        )
        """
    )
    (count,) = conn.execute("SELECT COUNT(*) FROM users").fetchone()
    if count == 0:
        conn.executemany(
            "INSERT INTO users (name, email, age) VALUES (?, ?, ?)",
            _SEED_USERS,
        )
    conn.commit()
