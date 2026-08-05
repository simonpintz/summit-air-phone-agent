"""SQLite-backed storage for bookings and urgent escalations.

Deliberately simple: a single file, stdlib sqlite3, no ORM. This is a
demo/take-home scheduler, not a production dispatch system - see README for
what a real integration (ServiceTitan/Housecall Pro, etc.) would replace here.
"""
from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./bookings.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    confirmation_number TEXT UNIQUE NOT NULL,
    call_id TEXT,
    customer_name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    address TEXT NOT NULL,
    property_type TEXT NOT NULL,
    issue_summary TEXT NOT NULL,
    urgency_level TEXT NOT NULL,
    vulnerable_occupant INTEGER NOT NULL DEFAULT 0,
    selected_window TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    customer_name TEXT,
    phone_number TEXT,
    address TEXT,
    reason TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);
"""


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA)


def _generate_confirmation_number() -> str:
    return "SA-" + secrets.token_hex(3).upper()


def create_booking(
    *,
    call_id: Optional[str],
    customer_name: str,
    phone_number: str,
    address: str,
    property_type: str,
    issue_summary: str,
    urgency_level: str,
    vulnerable_occupant: bool,
    selected_window: str,
    notes: Optional[str] = None,
) -> dict[str, Any]:
    confirmation_number = _generate_confirmation_number()
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO bookings (
                confirmation_number, call_id, customer_name, phone_number, address,
                property_type, issue_summary, urgency_level, vulnerable_occupant,
                selected_window, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                confirmation_number,
                call_id,
                customer_name,
                phone_number,
                address,
                property_type,
                issue_summary,
                urgency_level,
                1 if vulnerable_occupant else 0,
                selected_window,
                notes,
                created_at,
            ),
        )
    return {
        "confirmation_number": confirmation_number,
        "created_at": created_at,
    }


def create_escalation(
    *,
    call_id: Optional[str],
    customer_name: Optional[str],
    phone_number: Optional[str],
    address: Optional[str],
    reason: str,
    details: Optional[str] = None,
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO escalations (
                call_id, customer_name, phone_number, address, reason, details, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (call_id, customer_name, phone_number, address, reason, details, created_at),
        )
    return {"created_at": created_at}


def list_bookings(limit: int = 100) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM bookings ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def list_escalations(limit: int = 100) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM escalations ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
