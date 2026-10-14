


import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp_types import ElicitResult


import server


pytestmark = pytest.mark.requires_postgres


def make_elicitation_callback(approve: bool, seen: list):
    """Build a client elicitation callback that records prompts and replies."""

    async def callback(context, params):
        seen.append(params.message)

        if not approve:
            return ElicitResult(action="decline")

        return ElicitResult(action="accept", content={"approved": True})

    return callback


async def drive(call, elicitation_callback):
    """Run one client call against a freshly started server.

    Passing ``elicitation_callback=None`` models a client that advertises no
    elicitation capability.
    """

    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ), anyio.create_task_group() as tg:

        async def run_server():
            lowlevel = server.mcp._lowlevel_server
            await lowlevel.run(
                server_streams[0],
                server_streams[1],
                lowlevel.create_initialization_options(),
            )

        tg.start_soon(run_server)

        try:
            async with ClientSession(
                client_streams[0],
                client_streams[1],
                elicitation_callback=elicitation_callback,
            ) as session:
                await session.initialize()
                return await call(session)
        finally:
            tg.cancel_scope.cancel()


class TestDmlConfirmationEndToEnd:
    def test_a_read_tool_never_triggers_a_prompt(self):
        seen: list[str] = []

        async def call(session):
            return await session.call_tool(
                "list_schemas", {"database": "postgres"}
            )

        result = anyio.run(drive, call, make_elicitation_callback(True, seen))

        assert result.is_error is False
        assert seen == []

    def test_approval_executes_the_insert(self):
        seen: list[str] = []
        server.create_table("postgres", "mcp_confirm_insert", {"note": "VARCHAR(50)"})

        try:
            async def call(session):
                return await session.call_tool(
                    "insert_row",
                    {
                        "database": "postgres",
                        "table": "mcp_confirm_insert",
                        "data": {"note": "approved write"},
                    },
                )

            result = anyio.run(drive, call, make_elicitation_callback(True, seen))

            assert result.is_error is False
            assert len(seen) == 1
            assert "insert_row" in seen[0]
            assert "mcp_confirm_insert" in seen[0]
            assert "approved write" in seen[0]
            assert server.count_rows("postgres", "mcp_confirm_insert") == 1
        finally:
            server.delete_table("postgres", "mcp_confirm_insert")

    def test_a_decline_never_reaches_the_database(self):
        seen: list[str] = []
        server.create_table("postgres", "mcp_confirm_guard", {"id": "INTEGER"})

        try:
            async def call(session):
                return await session.call_tool(
                    "delete_table",
                    {
                        "database": "postgres",
                        "table": "mcp_confirm_guard",
                    },
                )

            result = anyio.run(drive, call, make_elicitation_callback(False, seen))

            assert result.is_error is True
            assert "declined" in result.content[0].text
            assert len(seen) == 1
            assert server.count_rows("postgres", "mcp_confirm_guard") == 0
        finally:
            server.delete_table("postgres", "mcp_confirm_guard")

    def test_an_approved_drop_actually_drops(self):
        seen: list[str] = []
        server.create_table("postgres", "mcp_confirm_approve", {"id": "INTEGER"})

        try:
            async def call(session):
                return await session.call_tool(
                    "delete_table",
                    {
                        "database": "postgres",
                        "table": "mcp_confirm_approve",
                    },
                )

            result = anyio.run(drive, call, make_elicitation_callback(True, seen))

            assert result.is_error is False
            assert len(seen) == 1
            assert "DESTRUCTIVE" in seen[0]

            with pytest.raises(ValueError):
                server.count_rows("postgres", "mcp_confirm_approve")
        finally:
            server.delete_table("postgres", "mcp_confirm_approve")

    def test_a_client_without_elicitation_support_is_refused(self):
        async def call(session):
            return await session.call_tool(
                "delete_table",
                {
                    "database": "postgres",
                    "table": "mcp_confirm_unsupported",
                },
            )

        result = anyio.run(drive, call, None)

        assert result.is_error is True
        assert "does not support elicitation" in result.content[0].text

    def test_each_mutating_call_is_gated_separately(self):
        seen: list[str] = []
        server.create_table("postgres", "mcp_confirm_twice", {"note": "VARCHAR(50)"})

        try:
            async def call(session):
                first = await session.call_tool(
                    "insert_row",
                    {
                        "database": "postgres",
                        "table": "mcp_confirm_twice",
                        "data": {"note": "one"},
                    },
                )
                second = await session.call_tool(
                    "insert_row",
                    {
                        "database": "postgres",
                        "table": "mcp_confirm_twice",
                        "data": {"note": "two"},
                    },
                )
                return first, second

            first, second = anyio.run(
                drive, call, make_elicitation_callback(True, seen)
            )

            assert first.is_error is False
            assert second.is_error is False
            assert len(seen) == 2
            assert server.count_rows("postgres", "mcp_confirm_twice") == 2
        finally:
            server.delete_table("postgres", "mcp_confirm_twice")
