"""SQLite persistence for users and transactions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator

import config


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                budget REAL,
                currency TEXT NOT NULL DEFAULT 'USD',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('income', 'expense')),
                amount REAL NOT NULL CHECK (amount > 0),
                category TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_user_created
            ON transactions (user_id, created_at);
            """
        )


def get_or_create_user(user_id: int) -> sqlite3.Row:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            now = _utc_now_iso()
            conn.execute(
                "INSERT INTO users (user_id, budget, currency, created_at) VALUES (?, NULL, 'USD', ?)",
                (user_id, now),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()
        assert row is not None
        return row


def set_budget(user_id: int, budget: float, currency: str = "USD") -> None:
    get_or_create_user(user_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET budget = ?, currency = ? WHERE user_id = ?",
            (budget, currency, user_id),
        )


def add_transaction(
    user_id: int,
    tx_type: str,
    amount: float,
    category: str,
    note: str | None = None,
    created_at: str | None = None,
) -> int:
    get_or_create_user(user_id)
    ts = created_at or _utc_now_iso()
    if created_at is not None:
        _parse_iso(ts)
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO transactions (user_id, type, amount, category, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, tx_type, amount, category, note, ts),
        )
        return int(cur.lastrowid)


def get_user_row(user_id: int) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()


def _parse_iso(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def sum_expenses_all_time(user_id: int) -> float:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
            WHERE user_id = ? AND type = 'expense'
            """,
            (user_id,),
        ).fetchone()
    return float(row["s"] if row else 0.0)


def sum_for_period(
    user_id: int,
    tx_type: str,
    days: int,
    end: datetime | None = None,
) -> float:
    end = end or datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    start_iso = start.replace(microsecond=0).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(amount), 0) AS s FROM transactions
            WHERE user_id = ? AND type = ? AND created_at >= ?
            """,
            (user_id, tx_type, start_iso),
        ).fetchone()
        return float(row["s"] if row else 0.0)


def get_expenses_by_category(user_id: int, days: int) -> dict[str, float]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    start_iso = start.replace(microsecond=0).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT category, SUM(amount) AS total FROM transactions
            WHERE user_id = ? AND type = 'expense' AND created_at >= ?
            GROUP BY category
            ORDER BY total DESC
            """,
            (user_id, start_iso),
        ).fetchall()
    return {str(r["category"]): float(r["total"]) for r in rows}


def get_recent_transactions(user_id: int, limit: int = 15) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, type, amount, category, note, created_at FROM transactions
            WHERE user_id = ?
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_balance_snapshot(user_id: int, period_days: int) -> dict[str, Any]:
    """Budget minus expenses in period; income listed separately."""
    row = get_user_row(user_id)
    budget = float(row["budget"]) if row and row["budget"] is not None else None
    currency = str(row["currency"]) if row else "USD"
    total_expense = sum_for_period(user_id, "expense", period_days)
    total_income = sum_for_period(user_id, "income", period_days)
    remaining = None
    if budget is not None:
        remaining = budget - total_expense
    return {
        "budget": budget,
        "currency": currency,
        "total_expense_period": total_expense,
        "total_income_period": total_income,
        "remaining_vs_budget": remaining,
        "expenses_by_category": get_expenses_by_category(user_id, period_days),
    }
