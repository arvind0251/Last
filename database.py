import sqlite3
import threading
from datetime import datetime, timedelta

from config import DB_PATH

_lock = threading.Lock()


def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock, _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS groups (
                group_id INTEGER PRIMARY KEY,
                title TEXT,
                invite_link TEXT,
                added_by INTEGER,
                added_at TEXT
            );

            CREATE TABLE IF NOT EXISTS plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER,
                label TEXT,
                days INTEGER,
                amount REAL
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                group_id INTEGER,
                plan_days INTEGER,
                start_date TEXT,
                end_date TEXT,
                status TEXT DEFAULT 'pending',
                order_id TEXT,
                amount REAL,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS payments (
                order_id TEXT PRIMARY KEY,
                user_id INTEGER,
                group_id INTEGER,
                plan_id INTEGER,
                amount REAL,
                days INTEGER,
                status TEXT DEFAULT 'created',
                txn_id TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        conn.commit()


# ---------------- GROUPS ----------------

def add_group(group_id, title, invite_link, added_by):
    with _lock, _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO groups (group_id, title, invite_link, added_by, added_at) VALUES (?,?,?,?,?)",
            (group_id, title, invite_link, added_by, datetime.utcnow().isoformat()),
        )
        conn.commit()


def get_group(group_id):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM groups WHERE group_id=?", (group_id,)).fetchone()
        return dict(row) if row else None


def list_groups():
    with _lock, _conn() as conn:
        rows = conn.execute("SELECT * FROM groups").fetchall()
        return [dict(r) for r in rows]


# ---------------- PLANS ----------------

def add_plan(group_id, label, days, amount):
    with _lock, _conn() as conn:
        cur = conn.execute(
            "INSERT INTO plans (group_id, label, days, amount) VALUES (?,?,?,?)",
            (group_id, label, days, amount),
        )
        conn.commit()
        return cur.lastrowid


def list_plans(group_id=None):
    with _lock, _conn() as conn:
        if group_id:
            rows = conn.execute("SELECT * FROM plans WHERE group_id=?", (group_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM plans").fetchall()
        return [dict(r) for r in rows]


def get_plan(plan_id):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        return dict(row) if row else None


def list_groups_with_plans():
    """Sirf wo groups jinke kam se kam 1 plan bana hua hai"""
    with _lock, _conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT g.group_id, g.title
               FROM groups g JOIN plans p ON g.group_id = p.group_id"""
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------- SUBSCRIPTIONS ----------------

def create_pending_subscription(user_id, group_id, days, order_id=None, amount=None):
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO subscriptions (user_id, group_id, plan_days, status, order_id, amount, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (user_id, group_id, days, "pending", order_id, amount, datetime.utcnow().isoformat()),
        )
        conn.commit()


def get_pending_subscription(user_id, group_id):
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=? AND group_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
            (user_id, group_id),
        ).fetchone()
        return dict(row) if row else None


def activate_subscription(sub_id, days):
    start = datetime.utcnow()
    end = start + timedelta(days=days)
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE subscriptions SET status='active', start_date=?, end_date=? WHERE id=?",
            (start.isoformat(), end.isoformat(), sub_id),
        )
        conn.commit()
    return start, end


def extend_subscription(user_id, group_id, extra_days):
    with _lock, _conn() as conn:
        row = conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=? AND group_id=? AND status='active' ORDER BY id DESC LIMIT 1",
            (user_id, group_id),
        ).fetchone()
        if row:
            cur_end = datetime.fromisoformat(row["end_date"])
            new_end = cur_end + timedelta(days=extra_days)
            conn.execute("UPDATE subscriptions SET end_date=? WHERE id=?", (new_end.isoformat(), row["id"]))
            conn.commit()
            return new_end
        return None


def revoke_subscription(user_id, group_id):
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE subscriptions SET status='revoked' WHERE user_id=? AND group_id=? AND status='active'",
            (user_id, group_id),
        )
        conn.commit()


def get_expired_subscriptions():
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subscriptions WHERE status='active' AND end_date<=?", (now,)
        ).fetchall()
        return [dict(r) for r in rows]


def mark_expired(sub_id):
    with _lock, _conn() as conn:
        conn.execute("UPDATE subscriptions SET status='expired' WHERE id=?", (sub_id,))
        conn.commit()


def list_subscriptions(group_id=None, status=None):
    q = "SELECT * FROM subscriptions WHERE 1=1"
    params = []
    if group_id:
        q += " AND group_id=?"
        params.append(group_id)
    if status:
        q += " AND status=?"
        params.append(status)
    with _lock, _conn() as conn:
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


# ---------------- PAYMENTS ----------------

def create_payment(order_id, user_id, group_id, plan_id, amount, days):
    with _lock, _conn() as conn:
        conn.execute(
            """INSERT INTO payments (order_id, user_id, group_id, plan_id, amount, days, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?, 'created', ?, ?)""",
            (order_id, user_id, group_id, plan_id, amount, days,
             datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
        )
        conn.commit()


def update_payment_status(order_id, status, txn_id=None):
    with _lock, _conn() as conn:
        conn.execute(
            "UPDATE payments SET status=?, txn_id=?, updated_at=? WHERE order_id=?",
            (status, txn_id, datetime.utcnow().isoformat(), order_id),
        )
        conn.commit()


def get_payment(order_id):
    with _lock, _conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE order_id=?", (order_id,)).fetchone()
        return dict(row) if row else None
