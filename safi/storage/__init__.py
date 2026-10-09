import datetime
import json
import sqlite3
import threading
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    version TEXT,
    source_path TEXT,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS instances (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    manifest TEXT NOT NULL,
    git_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS knowledge (
    knowledge_id TEXT PRIMARY KEY,
    service_expert_id TEXT NOT NULL,
    repo TEXT,
    branch TEXT,
    observed_at_sha TEXT,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    allowed_roles TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_scope ON knowledge(service_expert_id, category);
CREATE INDEX IF NOT EXISTS idx_knowledge_status ON knowledge(service_expert_id, verification_status);
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    service_expert_id TEXT NOT NULL,
    user_id TEXT,
    roles TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    context_knowledge_ids TEXT NOT NULL,
    llm_mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    # -- templates -------------------------------------------------------
    def upsert_template(self, template_id, version, source_path, content):
        self._execute(
            """INSERT INTO templates (id, version, source_path, content, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET version=excluded.version,
                 source_path=excluded.source_path, content=excluded.content""",
            (template_id, version, source_path, json.dumps(content), utcnow()),
        )

    def get_template(self, template_id):
        rows = self._query("SELECT * FROM templates WHERE id = ?", (template_id,))
        if not rows:
            return None
        row = rows[0]
        row["content"] = json.loads(row["content"])
        return row

    # -- instances -------------------------------------------------------
    def create_instance(self, instance_id, template_id, manifest, git_state):
        now = utcnow()
        self._execute(
            """INSERT INTO instances (id, template_id, manifest, git_state, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (instance_id, template_id, json.dumps(manifest), json.dumps(git_state), now, now),
        )

    def instance_exists(self, instance_id):
        return bool(self._query("SELECT id FROM instances WHERE id = ?", (instance_id,)))

    def get_instance(self, instance_id):
        rows = self._query("SELECT * FROM instances WHERE id = ?", (instance_id,))
        if not rows:
            return None
        row = rows[0]
        row["manifest"] = json.loads(row["manifest"])
        row["git_state"] = json.loads(row["git_state"])
        return row

    def list_instances(self):
        rows = self._query("SELECT id, template_id, created_at FROM instances ORDER BY created_at")
        return rows

    # -- knowledge -------------------------------------------------------
    def insert_knowledge(self, item):
        self._execute(
            """INSERT INTO knowledge
               (knowledge_id, service_expert_id, repo, branch, observed_at_sha, category,
                content, source, verification_status, allowed_roles, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["knowledge_id"],
                item["service_expert_id"],
                item.get("repo"),
                item.get("branch"),
                item.get("observed_at_sha"),
                item["category"],
                item["content"],
                item["source"],
                item["verification_status"],
                json.dumps(item.get("allowed_roles", [])),
                item.get("created_at") or utcnow(),
            ),
        )

    def list_knowledge(self, expert_ids, roles=None):
        """List knowledge for one or more experts.

        roles=None -> no RBAC filtering (internal use).
        roles=list -> only items whose allowed_roles intersect the roles.
        """
        if isinstance(expert_ids, str):
            expert_ids = [expert_ids]
        if not expert_ids:
            return []
        placeholders = ",".join("?" for _ in expert_ids)
        rows = self._query(
            f"SELECT * FROM knowledge WHERE service_expert_id IN ({placeholders})",
            tuple(expert_ids),
        )
        for row in rows:
            row["allowed_roles"] = json.loads(row["allowed_roles"])
        if roles is None:
            return rows
        role_set = set(roles)
        return [row for row in rows if role_set.intersection(row.get("allowed_roles") or [])]

    def get_knowledge(self, knowledge_id):
        rows = self._query("SELECT * FROM knowledge WHERE knowledge_id = ?", (knowledge_id,))
        if not rows:
            return None
        row = rows[0]
        row["allowed_roles"] = json.loads(row["allowed_roles"])
        return row

    def knowledge_count(self, expert_id):
        rows = self._query(
            "SELECT category, COUNT(*) AS n FROM knowledge WHERE service_expert_id = ? GROUP BY category",
            (expert_id,),
        )
        return {row["category"]: row["n"] for row in rows}

    def delete_knowledge_for(self, expert_id):
        self._execute("DELETE FROM knowledge WHERE service_expert_id = ?", (expert_id,))

    # -- sessions --------------------------------------------------------
    def insert_session(self, session):
        self._execute(
            """INSERT INTO sessions
               (session_id, service_expert_id, user_id, roles, question, answer,
                context_knowledge_ids, llm_mode, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["session_id"],
                session["service_expert_id"],
                session.get("user_id"),
                json.dumps(session.get("roles", [])),
                session["question"],
                session["answer"],
                json.dumps(session.get("context_knowledge_ids", [])),
                session["llm_mode"],
                session.get("created_at") or utcnow(),
            ),
        )

    def list_sessions(self, expert_id):
        rows = self._query(
            "SELECT * FROM sessions WHERE service_expert_id = ? ORDER BY created_at",
            (expert_id,),
        )
        for row in rows:
            row["roles"] = json.loads(row["roles"])
            row["context_knowledge_ids"] = json.loads(row["context_knowledge_ids"])
        return rows
