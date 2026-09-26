"""
NOOB's permanent memory.

Everything is stored in one SQLite database file on this PC (noob_memory.db).
It is free, needs no internet account, keeps private health information on your own
computer, and survives when NOOB or the PC is switched off.

Three tables:
  profile       - "About Me" details typed into the NOOB App (name, age, allergies, ...)
  facts         - important things the user told NOOB ("Asha is allergic to penicillin")
  conversation  - every question and answer, so NOOB can continue where it left off
"""

import sqlite3
import threading
from datetime import datetime


class NoobMemory:
    def __init__(self, path):
        self.lock = threading.Lock()
        # timeout: the NOOB App and the server can both use the file at the same time
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                saved_at TEXT NOT NULL,
                fact     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile (
                field TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversation (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                said_at TEXT NOT NULL,
                role    TEXT NOT NULL,          -- 'user' or 'assistant'
                text    TEXT NOT NULL
            );
        """)
        self.db.commit()

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---------------- profile ("About Me") ----------------
    def get_profile(self):
        with self.lock:
            return dict(self.db.execute("SELECT field, value FROM profile").fetchall())

    def set_profile(self, fields):
        """Replaces the whole profile. Empty values are not stored."""
        with self.lock:
            self.db.execute("DELETE FROM profile")
            self.db.executemany("INSERT INTO profile (field, value) VALUES (?, ?)",
                                [(k, v.strip()) for k, v in fields.items() if v and v.strip()])
            self.db.commit()

    # ---------------- facts ----------------
    def add_fact(self, fact):
        with self.lock:
            cur = self.db.execute("INSERT INTO facts (saved_at, fact) VALUES (?, ?)",
                                  (self._now(), fact.strip()))
            self.db.commit()
            return cur.lastrowid

    def update_fact(self, fact_id, fact):
        with self.lock:
            cur = self.db.execute("UPDATE facts SET fact = ? WHERE id = ?", (fact.strip(), fact_id))
            self.db.commit()
            return cur.rowcount > 0

    def delete_fact(self, fact_id):
        with self.lock:
            cur = self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            self.db.commit()
            return cur.rowcount > 0

    def all_facts(self):
        with self.lock:
            return self.db.execute("SELECT id, saved_at, fact FROM facts ORDER BY id").fetchall()

    # ---------------- conversation ----------------
    def add_exchange(self, user_text, reply):
        with self.lock:
            now = self._now()
            self.db.executemany("INSERT INTO conversation (said_at, role, text) VALUES (?, ?, ?)",
                                [(now, "user", user_text), (now, "assistant", reply)])
            self.db.commit()

    def recent_messages(self, limit):
        """The last `limit` messages, oldest first, always starting with a user message."""
        with self.lock:
            rows = self.db.execute("SELECT role, text FROM conversation ORDER BY id DESC LIMIT ?",
                                   (limit,)).fetchall()
        messages = [{"role": role, "content": text} for role, text in reversed(rows)]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    def recent_log(self, limit):
        with self.lock:
            rows = self.db.execute("SELECT said_at, role, text FROM conversation ORDER BY id DESC LIMIT ?",
                                   (limit,)).fetchall()
        return list(reversed(rows))

    def clear_conversation(self):
        with self.lock:
            self.db.execute("DELETE FROM conversation")
            self.db.commit()
