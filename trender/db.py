"""Prosta warstwa SQLite: cache odpowiedzi, profil, obserwowane frazy, wyniki i historia rynku."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any

from .catalog import seed_rows
from .profile import Profile, default_profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE,
    keyword_en TEXT,
    category TEXT,
    weight_g REAL NOT NULL,
    time_h REAL NOT NULL,
    filament TEXT,
    post_min REAL DEFAULT 0,
    color_changes INTEGER DEFAULT 0,
    seasons TEXT DEFAULT '["all_year"]',
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS opportunities (
    keyword_id INTEGER PRIMARY KEY REFERENCES keywords(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS market_history (
    keyword TEXT NOT NULL,
    day TEXT NOT NULL,
    total_listings INTEGER,
    median_price REAL,
    sold_sum INTEGER,
    trend_level REAL,
    PRIMARY KEY (keyword, day)
);
"""

KEYWORD_FIELDS = ("keyword", "keyword_en", "category", "weight_g", "time_h", "filament", "post_min",
                  "color_changes", "seasons", "active")


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            if not self.conn.execute("SELECT 1 FROM keywords LIMIT 1").fetchone():
                for row in seed_rows():
                    self._insert_keyword(row)
            self.conn.commit()

    # ------------------------------------------------ cache
    def cache_get(self, key: str) -> Any | None:
        with self.lock:
            row = self.conn.execute("SELECT value, expires_at FROM cache WHERE key=?", (key,)).fetchone()
        if not row or row["expires_at"] < time.time():
            return None
        return json.loads(row["value"])

    def cache_set(self, key: str, value: Any, ttl_s: float) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                              (key, json.dumps(value), time.time() + ttl_s))
            self.conn.commit()

    def cache_clear(self) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM cache")
            self.conn.commit()

    # ------------------------------------------------ profil
    def get_profile(self) -> Profile:
        with self.lock:
            row = self.conn.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
        return Profile.model_validate_json(row["value"]) if row else default_profile()

    def save_profile(self, profile: Profile) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO settings VALUES ('profile', ?)", (profile.model_dump_json(),))
            self.conn.commit()

    # ------------------------------------------------ frazy
    @staticmethod
    def _kw(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["seasons"] = json.loads(d["seasons"] or "[]")
        d["active"] = bool(d["active"])
        return d

    def _insert_keyword(self, data: dict) -> int:
        vals = {k: data.get(k) for k in KEYWORD_FIELDS if k in data}
        vals["seasons"] = json.dumps(vals.get("seasons") or ["all_year"])
        cols = ",".join(vals)
        cur = self.conn.execute(f"INSERT INTO keywords ({cols}) VALUES ({','.join('?' * len(vals))})",
                                tuple(vals.values()))
        return cur.lastrowid

    def list_keywords(self, active_only: bool = False) -> list[dict]:
        q = "SELECT * FROM keywords" + (" WHERE active=1" if active_only else "") + " ORDER BY keyword"
        with self.lock:
            return [self._kw(r) for r in self.conn.execute(q).fetchall()]

    def get_keyword(self, kid: int) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM keywords WHERE id=?", (kid,)).fetchone()
        return self._kw(r) if r else None

    def add_keyword(self, data: dict) -> dict:
        with self.lock:
            kid = self._insert_keyword(data)
            self.conn.commit()
        return self.get_keyword(kid)

    def update_keyword(self, kid: int, data: dict) -> dict | None:
        vals = {k: data[k] for k in KEYWORD_FIELDS if k in data}
        if "seasons" in vals:
            vals["seasons"] = json.dumps(vals["seasons"])
        if vals:
            with self.lock:
                self.conn.execute(f"UPDATE keywords SET {','.join(f'{k}=?' for k in vals)} WHERE id=?",
                                  (*vals.values(), kid))
                self.conn.commit()
        return self.get_keyword(kid)

    def delete_keyword(self, kid: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM keywords WHERE id=?", (kid,))
            self.conn.commit()

    # ------------------------------------------------ wyniki
    def save_opportunity(self, kid: int, data: dict) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO opportunities VALUES (?,?,?)",
                              (kid, json.dumps(data), time.time()))
            self.conn.commit()

    def list_opportunities(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT o.data, o.updated_at FROM opportunities o JOIN keywords k ON k.id=o.keyword_id "
                "WHERE k.active=1").fetchall()
        out = []
        for r in rows:
            d = json.loads(r["data"])
            d["updated_at"] = r["updated_at"]
            out.append(d)
        return out

    def record_history(self, keyword: str, day: str, total: int | None, median: float | None,
                       sold: int | None, trend_level: float | None) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO market_history VALUES (?,?,?,?,?,?)",
                              (keyword, day, total, median, sold, trend_level))
            self.conn.commit()

    def history(self, keyword: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM market_history WHERE keyword=? ORDER BY day",
                                     (keyword,)).fetchall()
        return [dict(r) for r in rows]
