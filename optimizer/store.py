import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, created TEXT, kind TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS network_events (id INTEGER PRIMARY KEY, created TEXT, payload TEXT);
                CREATE TABLE IF NOT EXISTS actions (id INTEGER PRIMARY KEY, created TEXT, action TEXT,
                    status TEXT, payload TEXT);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def get(self, key, default=None):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.lock, self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def action(self, name, status, payload):
        with self.lock, self.connect() as db:
            c = db.execute("INSERT INTO actions(created,action,status,payload) VALUES (?,?,?,?)",
                           (timestamp(), name, status, json.dumps(payload)))
            return c.lastrowid

    def actions(self):
        with self.lock, self.connect() as db:
            return [dict(id=r[0], created=r[1], action=r[2], status=r[3], payload=json.loads(r[4]))
                    for r in db.execute("SELECT * FROM actions ORDER BY id DESC LIMIT 500")]

    def save_run(self, kind, payload):
        with self.lock, self.connect() as db:
            c = db.execute("INSERT INTO runs(created,kind,payload) VALUES (?,?,?)",
                           (timestamp(), kind, json.dumps(payload)))
            return c.lastrowid

    def runs(self):
        with self.lock, self.connect() as db:
            return [dict(id=r[0], created=r[1], kind=r[2], payload=json.loads(r[3]))
                    for r in db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 500")]

    def save_diagnostic_event(self, payload):
        with self.lock, self.connect() as db:
            c = db.execute("INSERT INTO network_events(created,payload) VALUES (?,?)",
                           (timestamp(), json.dumps(payload)))
            return c.lastrowid

    def diagnostic_events(self, limit=200):
        with self.lock, self.connect() as db:
            return [dict(id=r[0], created=r[1], payload=json.loads(r[2])) for r in db.execute(
                "SELECT id,created,payload FROM network_events ORDER BY id DESC LIMIT ?", (limit,))]
