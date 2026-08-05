"""Private SQLite storage boundary for the portable learning loop."""

import os
import sqlite3
import time
from pathlib import Path


DEFAULT_LEARNING_DB = Path(__file__).resolve().parent / "learning.db"
SCHEMA_VERSION = 2


def learning_db_path() -> Path:
    return Path(os.environ.get("AGENT_LEARNING_DB", str(DEFAULT_LEARNING_DB)))


def enforce_permissions(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-shm"), Path(str(path) + "-wal")):
        if candidate.exists():
            candidate.chmod(0o600)


def _create_schema_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS learning_schema (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS review_batches (
            id TEXT PRIMARY KEY,
            operator_id TEXT NOT NULL,
            source_harness TEXT NOT NULL,
            source_session_id TEXT NOT NULL,
            reviewing_agent_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN (
                    'open', 'completed', 'skipped_unrenderable',
                    'delivery_failed'
                )
            ),
            created_at REAL NOT NULL,
            surfaced_at REAL,
            surface_count INTEGER NOT NULL DEFAULT 0 CHECK (
                surface_count BETWEEN 0 AND 2
            ),
            completed_at REAL,
            terminal_at REAL,
            terminal_reason TEXT,
            CHECK (
                (
                    status = 'open'
                    AND completed_at IS NULL
                    AND terminal_at IS NULL
                    AND terminal_reason IS NULL
                )
                OR (
                    status = 'completed'
                    AND completed_at IS NOT NULL
                    AND terminal_at IS NULL
                    AND terminal_reason IS NULL
                )
                OR (
                    status IN ('skipped_unrenderable', 'delivery_failed')
                    AND completed_at IS NULL
                    AND terminal_at IS NOT NULL
                    AND length(trim(terminal_reason)) > 0
                )
            )
        );

        CREATE UNIQUE INDEX IF NOT EXISTS one_open_review_batch
        ON review_batches(operator_id, source_harness, source_session_id)
        WHERE status = 'open';

        CREATE TABLE IF NOT EXISTS review_batch_items (
            batch_id TEXT NOT NULL,
            harness TEXT NOT NULL,
            session_id TEXT NOT NULL,
            message_key TEXT NOT NULL,
            message_content_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            timestamp REAL NOT NULL,
            order_index INTEGER NOT NULL,
            PRIMARY KEY (batch_id, order_index),
            UNIQUE (
                batch_id,
                harness,
                session_id,
                message_key,
                message_content_hash
            ),
            FOREIGN KEY (batch_id) REFERENCES review_batches(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS learning_claims (
            id TEXT PRIMARY KEY,
            operator_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind = 'preference'),
            statement TEXT NOT NULL,
            scope TEXT NOT NULL CHECK (
                scope IN ('global', 'communication', 'work_style', 'domain')
            ),
            scope_key TEXT,
            status TEXT NOT NULL CHECK (
                status IN ('provisional', 'confirmed', 'rejected', 'superseded')
            ),
            confidence TEXT NOT NULL CHECK (confidence IN ('explicit', 'inferred')),
            created_by_agent_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            first_observed_at REAL NOT NULL,
            last_observed_at REAL NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            UNIQUE (operator_id, content_hash),
            CHECK (
                (scope = 'domain' AND scope_key IS NOT NULL AND length(trim(scope_key)) > 0)
                OR (scope != 'domain' AND scope_key IS NULL)
            )
        );

        CREATE TABLE IF NOT EXISTS claim_evidence (
            id INTEGER PRIMARY KEY,
            claim_id TEXT NOT NULL,
            harness TEXT NOT NULL,
            session_id TEXT NOT NULL,
            message_key TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role = 'user'),
            quote TEXT NOT NULL CHECK (length(quote) <= 500),
            message_content_hash TEXT NOT NULL,
            timestamp REAL NOT NULL,
            UNIQUE (
                claim_id,
                harness,
                session_id,
                message_key,
                message_content_hash,
                quote
            ),
            FOREIGN KEY (claim_id) REFERENCES learning_claims(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS learning_message_state (
            operator_id TEXT NOT NULL,
            harness TEXT NOT NULL,
            session_id TEXT NOT NULL,
            message_key TEXT NOT NULL,
            message_content_hash TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            disposition TEXT NOT NULL CHECK (
                disposition IN (
                    'reviewed', 'baseline_skipped', 'skipped_unrenderable',
                    'delivery_failed'
                )
            ),
            recorded_at REAL NOT NULL,
            PRIMARY KEY (
                operator_id,
                harness,
                session_id,
                message_key,
                message_content_hash
            ),
            FOREIGN KEY (batch_id) REFERENCES review_batches(id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS learning_claims_fts USING fts5(
            statement,
            scope,
            scope_key,
            content='learning_claims',
            content_rowid='rowid',
            tokenize='porter unicode61'
        );

        CREATE TRIGGER IF NOT EXISTS learning_claims_insert
        AFTER INSERT ON learning_claims BEGIN
            INSERT INTO learning_claims_fts(rowid, statement, scope, scope_key)
            VALUES (new.rowid, new.statement, new.scope, new.scope_key);
        END;

        CREATE TRIGGER IF NOT EXISTS learning_claims_delete
        AFTER DELETE ON learning_claims BEGIN
            INSERT INTO learning_claims_fts(
                learning_claims_fts,
                rowid,
                statement,
                scope,
                scope_key
            ) VALUES (
                'delete',
                old.rowid,
                old.statement,
                old.scope,
                old.scope_key
            );
        END;

        CREATE TRIGGER IF NOT EXISTS learning_claims_update
        AFTER UPDATE OF statement, scope, scope_key ON learning_claims BEGIN
            INSERT INTO learning_claims_fts(
                learning_claims_fts,
                rowid,
                statement,
                scope,
                scope_key
            ) VALUES (
                'delete',
                old.rowid,
                old.statement,
                old.scope,
                old.scope_key
            );
            INSERT INTO learning_claims_fts(rowid, statement, scope, scope_key)
            VALUES (new.rowid, new.statement, new.scope, new.scope_key);
        END;
        """
    )


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DROP INDEX IF EXISTS one_open_review_batch")
        conn.execute(
            """
            CREATE TABLE review_batches_v2 (
                id TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL,
                source_harness TEXT NOT NULL,
                source_session_id TEXT NOT NULL,
                reviewing_agent_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN (
                        'open', 'completed', 'skipped_unrenderable',
                        'delivery_failed'
                    )
                ),
                created_at REAL NOT NULL,
                surfaced_at REAL,
                surface_count INTEGER NOT NULL DEFAULT 0 CHECK (
                    surface_count BETWEEN 0 AND 2
                ),
                completed_at REAL,
                terminal_at REAL,
                terminal_reason TEXT,
                CHECK (
                    (
                        status = 'open'
                        AND completed_at IS NULL
                        AND terminal_at IS NULL
                        AND terminal_reason IS NULL
                    )
                    OR (
                        status = 'completed'
                        AND completed_at IS NOT NULL
                        AND terminal_at IS NULL
                        AND terminal_reason IS NULL
                    )
                    OR (
                        status IN ('skipped_unrenderable', 'delivery_failed')
                        AND completed_at IS NULL
                        AND terminal_at IS NOT NULL
                        AND length(trim(terminal_reason)) > 0
                    )
                )
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE review_batch_items_v2 (
                batch_id TEXT NOT NULL,
                harness TEXT NOT NULL,
                session_id TEXT NOT NULL,
                message_key TEXT NOT NULL,
                message_content_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                timestamp REAL NOT NULL,
                order_index INTEGER NOT NULL,
                PRIMARY KEY (batch_id, order_index),
                UNIQUE (
                    batch_id,
                    harness,
                    session_id,
                    message_key,
                    message_content_hash
                ),
                FOREIGN KEY (batch_id)
                    REFERENCES review_batches_v2(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE learning_message_state_v2 (
                operator_id TEXT NOT NULL,
                harness TEXT NOT NULL,
                session_id TEXT NOT NULL,
                message_key TEXT NOT NULL,
                message_content_hash TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                disposition TEXT NOT NULL CHECK (
                    disposition IN (
                        'reviewed', 'baseline_skipped',
                        'skipped_unrenderable', 'delivery_failed'
                    )
                ),
                recorded_at REAL NOT NULL,
                PRIMARY KEY (
                    operator_id,
                    harness,
                    session_id,
                    message_key,
                    message_content_hash
                ),
                FOREIGN KEY (batch_id) REFERENCES review_batches_v2(id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO review_batches_v2(
                id, operator_id, source_harness, source_session_id,
                reviewing_agent_id, status, created_at, completed_at
            )
            SELECT
                id, operator_id, source_harness, source_session_id,
                reviewing_agent_id, status, created_at, completed_at
            FROM review_batches
            """
        )
        conn.execute(
            """
            INSERT INTO review_batch_items_v2
            SELECT * FROM review_batch_items
            """
        )
        conn.execute(
            """
            INSERT INTO learning_message_state_v2
            SELECT * FROM learning_message_state
            """
        )
        conn.execute("DROP TABLE learning_message_state")
        conn.execute("DROP TABLE review_batch_items")
        conn.execute("DROP TABLE review_batches")
        conn.execute("ALTER TABLE review_batches_v2 RENAME TO review_batches")
        conn.execute(
            "ALTER TABLE review_batch_items_v2 RENAME TO review_batch_items"
        )
        conn.execute(
            "ALTER TABLE learning_message_state_v2 "
            "RENAME TO learning_message_state"
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX one_open_review_batch
            ON review_batches(operator_id, source_harness, source_session_id)
            WHERE status = 'open'
            """
        )
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                "learning schema migration left foreign-key violations"
            )
        conn.execute(
            "INSERT INTO learning_schema(version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, time.time()),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS learning_schema (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        )
        """
    )
    version_row = conn.execute(
        "SELECT MAX(version) FROM learning_schema"
    ).fetchone()
    version = int(version_row[0]) if version_row and version_row[0] else None
    has_batches = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'review_batches'
        """
    ).fetchone()
    if has_batches and version is None:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(review_batches)")
        }
        version = 2 if "surface_count" in columns else 1
    if has_batches and version == 1:
        _migrate_v1_to_v2(conn)
    elif version not in (None, SCHEMA_VERSION):
        raise sqlite3.DatabaseError(
            "unsupported learning schema version %s" % version
        )

    _create_schema_v2(conn)
    conn.execute(
        "INSERT OR IGNORE INTO learning_schema(version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, time.time()),
    )


def connect_learning() -> tuple[sqlite3.Connection, Path]:
    path = learning_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(descriptor)
    path.chmod(0o600)
    conn = sqlite3.connect(path, timeout=2.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=2000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    conn.commit()
    enforce_permissions(path)
    return conn, path
