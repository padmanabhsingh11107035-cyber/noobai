"""
NOOB's permanent memory.

Everything is stored in one SQLite database file on this PC (noob_memory.db).
It is free, needs no internet account, keeps private health information on your own
computer, and survives when NOOB or the PC is switched off.

Tables:
  users         - NOOB App accounts (passwords are stored only as secure hashes; an account can be
                  linked to a NOOB social media account for "Continue with NOOB")
  profile       - each user's "About Me" details (name, age, allergies, ...)
  facts         - important things each user told NOOB ("Asha is allergic to penicillin")
  conversation  - every question and answer, so NOOB can continue where it left off
  moods         - how the user seemed to feel (noticed by the AI from their words and tone of voice)
  reviews       - the 5-star ratings people give NOOB AI
"""

import os
import shutil
import sqlite3
import threading
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash


class NoobMemory:
    def __init__(self, path):
        self.lock = threading.Lock()
        existed = os.path.exists(path) and os.path.getsize(path) > 0
        # timeout: the server threads can use the file at the same time
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        if existed and self._needs_upgrade():
            self.db.close()                                   # safety first: keep a copy of the old memory
            shutil.copy2(path, path[:-3] + f".backup-{datetime.now():%Y%m%d-%H%M%S}.db")
            self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
            self._upgrade()
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT NOT NULL UNIQUE,
                name       TEXT NOT NULL,
                pw_hash    TEXT NOT NULL,
                is_owner   INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile (
                user_id INTEGER NOT NULL,
                field   TEXT NOT NULL,
                value   TEXT NOT NULL,
                PRIMARY KEY (user_id, field)
            );
            CREATE TABLE IF NOT EXISTS facts (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                saved_at TEXT NOT NULL,
                fact     TEXT NOT NULL,
                user_id  INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS conversation (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                said_at TEXT NOT NULL,
                role    TEXT NOT NULL,          -- 'user' or 'assistant'
                text    TEXT NOT NULL,
                user_id INTEGER NOT NULL DEFAULT 1
            );
        """)
        if "noob_id" not in self._columns("users"):          # "Continue with NOOB" link
            self.db.execute("ALTER TABLE users ADD COLUMN noob_id TEXT")
            self.db.execute("ALTER TABLE users ADD COLUMN noob_username TEXT")
        if "questions" not in self._columns("users"):        # questions asked (free limit, survey)
            self.db.execute("ALTER TABLE users ADD COLUMN questions INTEGER NOT NULL DEFAULT 0")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS moods (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                at      TEXT NOT NULL,
                mood    TEXT NOT NULL,
                score   INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                at      TEXT NOT NULL,
                stars   INTEGER NOT NULL,
                comment TEXT NOT NULL DEFAULT ''
            );
        """)
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_noob_id ON users (noob_id) WHERE noob_id IS NOT NULL")
        self.db.commit()

    # ---------------- upgrade from the single-user version (keeps all data for the first account)
    def _columns(self, table):
        return [row[1] for row in self.db.execute(f"PRAGMA table_info({table})")]

    def _tables(self):
        return {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def _needs_upgrade(self):
        tables = self._tables()
        return any(t in tables and "user_id" not in self._columns(t) for t in ("facts", "conversation", "profile"))

    def _upgrade(self):
        with self.db:                                         # one transaction: all or nothing
            tables = self._tables()
            for table in ("facts", "conversation"):
                if table in tables and "user_id" not in self._columns(table):
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")
            if "profile" in tables and "user_id" not in self._columns("profile"):
                self.db.execute("CREATE TABLE profile_new (user_id INTEGER NOT NULL, field TEXT NOT NULL, "
                                "value TEXT NOT NULL, PRIMARY KEY (user_id, field))")
                self.db.execute("INSERT INTO profile_new (user_id, field, value) SELECT 1, field, value FROM profile")
                self.db.execute("DROP TABLE profile")
                self.db.execute("ALTER TABLE profile_new RENAME TO profile")

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---------------- accounts ----------------
    def user_count(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def username_free(self, username):
        with self.lock:
            return not self.db.execute("SELECT 1 FROM users WHERE username = ?", (username.lower(),)).fetchone()

    def create_user(self, username, name, password):
        """Returns the new user's id, or None if the username is taken.
        The first account becomes the owner and keeps the memory saved before accounts existed."""
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM users WHERE username = ?", (username.lower(),)).fetchone():
                return None
            first = self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            cur = self.db.execute(
                "INSERT INTO users (username, name, pw_hash, is_owner, created_at) VALUES (?, ?, ?, ?, ?)",
                (username.lower(), name, generate_password_hash(password), int(first), self._now()))
            user_id = cur.lastrowid
            if first and user_id != 1:                        # memory saved before accounts existed
                for table in ("facts", "conversation", "profile"):
                    self.db.execute(f"UPDATE {table} SET user_id = ? WHERE user_id = 1", (user_id,))
            return user_id

    def check_login(self, username, password):
        with self.lock:
            row = self.db.execute("SELECT id, pw_hash FROM users WHERE username = ?", (username.lower(),)).fetchone()
        if row and check_password_hash(row[1], password):
            return row[0]
        return None

    USER_FIELDS = ("id", "username", "name", "is_owner", "created_at", "noob_username", "questions")

    def get_user(self, user_id):
        with self.lock:
            row = self.db.execute(f"SELECT {', '.join(self.USER_FIELDS)} FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(zip(self.USER_FIELDS, row)) if row else None

    def all_users(self):
        with self.lock:
            rows = self.db.execute(f"SELECT {', '.join(self.USER_FIELDS)} FROM users ORDER BY id").fetchall()
        return [dict(zip(self.USER_FIELDS, r)) for r in rows]

    # ---------------- "Continue with NOOB" ----------------
    def user_for_noob(self, noob_id):
        with self.lock:
            row = self.db.execute("SELECT id FROM users WHERE noob_id = ?", (noob_id,)).fetchone()
        return row[0] if row else None

    def link_noob(self, user_id, noob_id, noob_username):
        """Links a NOOB social account. Returns False if it is already linked to another account."""
        with self.lock, self.db:
            other = self.db.execute("SELECT id FROM users WHERE noob_id = ?", (noob_id,)).fetchone()
            if other and other[0] != user_id:
                return False
            self.db.execute("UPDATE users SET noob_id = ?, noob_username = ? WHERE id = ?", (noob_id, noob_username, user_id))
            return True

    def change_password(self, user_id, password):
        with self.lock, self.db:
            self.db.execute("UPDATE users SET pw_hash = ? WHERE id = ?", (generate_password_hash(password), user_id))

    def delete_user(self, user_id):
        """Deletes an account and all of its data (never the owner). Returns True if deleted."""
        with self.lock, self.db:
            cur = self.db.execute("DELETE FROM users WHERE id = ? AND is_owner = 0", (user_id,))
            if cur.rowcount:
                for table in ("facts", "conversation", "profile", "moods", "reviews"):
                    self.db.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            return cur.rowcount > 0

    # ---------------- questions, moods and ratings ----------------
    def count_question(self, user_id):
        """Adds one to the user's questions and returns the new total."""
        with self.lock, self.db:
            self.db.execute("UPDATE users SET questions = questions + 1 WHERE id = ?", (user_id,))
            row = self.db.execute("SELECT questions FROM users WHERE id = ?", (user_id,)).fetchone()
        return row[0] if row else 0

    def add_mood(self, user_id, mood, score):
        with self.lock, self.db:
            self.db.execute("INSERT INTO moods (user_id, at, mood, score) VALUES (?, ?, ?, ?)",
                            (user_id, self._now(), mood, score))

    def recent_moods(self, user_id, limit=30):
        with self.lock:
            rows = self.db.execute("SELECT at, mood, score FROM moods WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                                   (user_id, limit)).fetchall()
        return list(reversed(rows))

    def clear_moods(self, user_id):
        with self.lock, self.db:
            self.db.execute("DELETE FROM moods WHERE user_id = ?", (user_id,))

    def has_reviewed(self, user_id):
        with self.lock:
            return self.db.execute("SELECT 1 FROM reviews WHERE user_id = ?", (user_id,)).fetchone() is not None

    def add_review(self, user_id, stars, comment):
        with self.lock, self.db:
            self.db.execute("INSERT INTO reviews (user_id, at, stars, comment) VALUES (?, ?, ?, ?)",
                            (user_id, self._now(), stars, comment))

    def reviews_summary(self, limit=20):
        with self.lock:
            count, average = self.db.execute("SELECT COUNT(*), AVG(stars) FROM reviews").fetchone()
            rows = self.db.execute("SELECT r.at, r.stars, r.comment, COALESCE(u.name, 'Someone') FROM reviews r "
                                   "LEFT JOIN users u ON u.id = r.user_id ORDER BY r.id DESC LIMIT ?", (limit,)).fetchall()
        return {"count": count, "average": round(average, 1) if average else None,
                "latest": [{"at": a, "stars": st, "comment": c, "name": n} for a, st, c, n in rows]}

    # ---------------- profile ("About Me") ----------------
    def get_profile(self, user_id):
        with self.lock:
            return dict(self.db.execute("SELECT field, value FROM profile WHERE user_id = ?", (user_id,)).fetchall())

    def set_profile(self, user_id, fields):
        """Replaces the user's whole profile. Empty values are not stored."""
        with self.lock, self.db:
            self.db.execute("DELETE FROM profile WHERE user_id = ?", (user_id,))
            self.db.executemany("INSERT INTO profile (user_id, field, value) VALUES (?, ?, ?)",
                                [(user_id, k, v.strip()) for k, v in fields.items() if v and v.strip()])

    # ---------------- facts ----------------
    def add_fact(self, user_id, fact):
        with self.lock, self.db:
            cur = self.db.execute("INSERT INTO facts (saved_at, fact, user_id) VALUES (?, ?, ?)",
                                  (self._now(), fact.strip(), user_id))
            return cur.lastrowid

    def update_fact(self, user_id, fact_id, fact):
        with self.lock, self.db:
            cur = self.db.execute("UPDATE facts SET fact = ? WHERE id = ? AND user_id = ?",
                                  (fact.strip(), fact_id, user_id))
            return cur.rowcount > 0

    def delete_fact(self, user_id, fact_id):
        with self.lock, self.db:
            cur = self.db.execute("DELETE FROM facts WHERE id = ? AND user_id = ?", (fact_id, user_id))
            return cur.rowcount > 0

    def all_facts(self, user_id):
        with self.lock:
            return self.db.execute("SELECT id, saved_at, fact FROM facts WHERE user_id = ? ORDER BY id",
                                   (user_id,)).fetchall()

    # ---------------- conversation ----------------
    def add_exchange(self, user_id, user_text, reply):
        with self.lock, self.db:
            now = self._now()
            self.db.executemany("INSERT INTO conversation (said_at, role, text, user_id) VALUES (?, ?, ?, ?)",
                                [(now, "user", user_text, user_id), (now, "assistant", reply, user_id)])

    def recent_messages(self, user_id, limit):
        """The user's last `limit` messages, oldest first, always starting with a user message."""
        with self.lock:
            rows = self.db.execute("SELECT role, text FROM conversation WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                                   (user_id, limit)).fetchall()
        messages = [{"role": role, "content": text} for role, text in reversed(rows)]
        while messages and messages[0]["role"] != "user":
            messages.pop(0)
        return messages

    def recent_log(self, user_id, limit):
        with self.lock:
            rows = self.db.execute("SELECT said_at, role, text FROM conversation WHERE user_id = ? "
                                   "ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
        return list(reversed(rows))

    def clear_conversation(self, user_id):
        with self.lock, self.db:
            self.db.execute("DELETE FROM conversation WHERE user_id = ?", (user_id,))
