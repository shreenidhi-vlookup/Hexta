"""Integration test for self-service client assignment (Stage 2 Task 6).

A processor assigns *themselves* to a client, never anyone else -- the
point of the whole task is removing the admin bottleneck without opening
a way for one user to grant another access. Every endpoint operates on
a real row in ``users`` via the actual SQL, not a mock, since the thing
under test is exactly "does the WHERE clause only ever touch the
caller's own id."
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.api.v1 import me
from app.db.postgres.schema import ensure_schema
from app.db.postgres.session import acquire


def _db_available() -> bool:
    try:
        from app.db.postgres.session import ping
        return ping()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(),
    reason="Requires a running Postgres instance with hexa_assistant schema",
)


@pytest.fixture
def processor_row():
    """A real processor user row, cleaned up after the test."""
    ensure_schema()
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM users WHERE email = %s",
                ("me-clients-test@hexa.local",),
            )
            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "assigned_clients) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (
                    "me-clients-test@hexa.local",
                    "x",
                    "processor",
                    "general",
                    [],
                ),
            )
            user_id = cur.fetchone()["id"]
        conn.commit()

    yield {"id": user_id, "role": "processor", "assigned_clients": []}

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()


@pytest.fixture
def other_processor_row():
    """A second user, to prove one caller can never touch another's row."""
    ensure_schema()
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM users WHERE email = %s",
                ("me-clients-other@hexa.local",),
            )
            cur.execute(
                "INSERT INTO users (email, password_hash, role, department, "
                "assigned_clients) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                ("me-clients-other@hexa.local", "x", "processor", "general", []),
            )
            other_id = cur.fetchone()["id"]
        conn.commit()

    yield {"id": other_id, "role": "processor", "assigned_clients": []}

    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (other_id,))
        conn.commit()


def _assigned_clients_in_db(user_id: int) -> list[str]:
    with acquire() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT assigned_clients FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
    return list(row["assigned_clients"] or []) if row else []


class TestListMyClients:
    def test_starts_empty(self, processor_row):
        result = asyncio.run(me.list_my_clients(user=processor_row))
        assert result == {"assigned_clients": []}

    def test_client_role_is_rejected(self, processor_row):
        client_user = {**processor_row, "role": "client"}
        with pytest.raises(HTTPException) as exc:
            asyncio.run(me.list_my_clients(user=client_user))
        assert exc.value.status_code == 403


class TestAssignMyClient:
    def test_assigns_to_own_row(self, processor_row):
        body = me.ClientAssignment(client_id="CLIENT_A")
        result = asyncio.run(me.assign_my_client(body=body, user=processor_row))
        assert result == {"assigned_clients": ["CLIENT_A"]}
        assert _assigned_clients_in_db(processor_row["id"]) == ["CLIENT_A"]

    def test_is_idempotent(self, processor_row):
        body = me.ClientAssignment(client_id="CLIENT_A")
        asyncio.run(me.assign_my_client(body=body, user=processor_row))
        result = asyncio.run(me.assign_my_client(body=body, user=processor_row))
        assert result == {"assigned_clients": ["CLIENT_A"]}

    def test_accumulates_multiple_clients(self, processor_row):
        asyncio.run(me.assign_my_client(
            body=me.ClientAssignment(client_id="CLIENT_A"), user=processor_row,
        ))
        result = asyncio.run(me.assign_my_client(
            body=me.ClientAssignment(client_id="CLIENT_B"), user=processor_row,
        ))
        assert set(result["assigned_clients"]) == {"CLIENT_A", "CLIENT_B"}

    def test_never_touches_another_users_row(
        self, processor_row, other_processor_row,
    ):
        """The point of the task: nothing in the request can name a
        different user. Assigning as processor_row must never appear on
        other_processor_row's own record."""
        asyncio.run(me.assign_my_client(
            body=me.ClientAssignment(client_id="CLIENT_A"), user=processor_row,
        ))
        assert _assigned_clients_in_db(other_processor_row["id"]) == []

    def test_client_role_is_rejected(self, processor_row):
        client_user = {**processor_row, "role": "client"}
        with pytest.raises(HTTPException) as exc:
            asyncio.run(me.assign_my_client(
                body=me.ClientAssignment(client_id="CLIENT_A"), user=client_user,
            ))
        assert exc.value.status_code == 403

    def test_blank_client_id_is_rejected(self, processor_row):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(me.assign_my_client(
                body=me.ClientAssignment(client_id="   "), user=processor_row,
            ))
        assert exc.value.status_code == 400


class TestReleaseMyClient:
    def test_releases_an_assigned_client(self, processor_row):
        asyncio.run(me.assign_my_client(
            body=me.ClientAssignment(client_id="CLIENT_A"), user=processor_row,
        ))
        result = asyncio.run(
            me.release_my_client(client_id="CLIENT_A", user=processor_row)
        )
        assert result == {"assigned_clients": []}
        assert _assigned_clients_in_db(processor_row["id"]) == []

    def test_releasing_an_unassigned_client_is_a_noop(self, processor_row):
        result = asyncio.run(
            me.release_my_client(client_id="NEVER_ASSIGNED", user=processor_row)
        )
        assert result == {"assigned_clients": []}

    def test_releasing_one_client_leaves_others(self, processor_row):
        asyncio.run(me.assign_my_client(
            body=me.ClientAssignment(client_id="CLIENT_A"), user=processor_row,
        ))
        asyncio.run(me.assign_my_client(
            body=me.ClientAssignment(client_id="CLIENT_B"), user=processor_row,
        ))
        result = asyncio.run(
            me.release_my_client(client_id="CLIENT_A", user=processor_row)
        )
        assert result == {"assigned_clients": ["CLIENT_B"]}

    def test_never_touches_another_users_row(
        self, processor_row, other_processor_row,
    ):
        asyncio.run(me.assign_my_client(
            body=me.ClientAssignment(client_id="CLIENT_A"), user=other_processor_row,
        ))
        asyncio.run(
            me.release_my_client(client_id="CLIENT_A", user=processor_row)
        )
        assert _assigned_clients_in_db(other_processor_row["id"]) == ["CLIENT_A"]

    def test_client_role_is_rejected(self, processor_row):
        client_user = {**processor_row, "role": "client"}
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                me.release_my_client(client_id="CLIENT_A", user=client_user)
            )
        assert exc.value.status_code == 403
