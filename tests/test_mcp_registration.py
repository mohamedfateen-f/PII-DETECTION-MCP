"""Tests for the MCP tool registry and the MCP protocol call path."""

import asyncio

import pytest

from mcp.server.mcpserver.exceptions import UnexpectedToolError

import server

pytestmark = pytest.mark.requires_postgres

EXPECTED_TOOLS = [
    "list_databases",
    "create_database",
    "delete_database",
    "database_info",
    "list_schemas",
    "list_tables",
    "describe_table",
    "read_table",
    "query",
    "count_rows",
    "insert_row",
    "insert_rows",
    "update_rows",
    "delete_rows",
    "table_stats",
    "anonymize_and_insert",
    "anonymized_update",
    "anonymize_and_insert_rows",
    "anonymized_delete",
    "create_table",
    "delete_table",
    "alter_table",
    "upsert_row",
]


def test_all_expected_tools_are_registered():
    tools = asyncio.run(server.mcp.list_tools())

    assert [tool.name for tool in tools] == EXPECTED_TOOLS


def test_every_tool_exposes_a_description():
    tools = asyncio.run(server.mcp.list_tools())

    for tool in tools:
        assert tool.description, tool.name


def test_query_tool_schema_requires_database_and_sql():
    tools = asyncio.run(server.mcp.list_tools())
    query_tool = next(tool for tool in tools if tool.name == "query")

    assert set(query_tool.input_schema["required"]) == {"database", "sql_query"}
    assert set(query_tool.input_schema["properties"]) == {"database", "sql_query"}


def test_list_tables_schema_has_default_schema_argument():
    tools = asyncio.run(server.mcp.list_tools())
    tool = next(tool for tool in tools if tool.name == "list_tables")

    assert tool.input_schema["properties"]["schema"]["default"] == "public"
    assert "schema" not in tool.input_schema["required"]


def test_call_tool_returns_structured_result():
    result = asyncio.run(
        server.mcp.call_tool("list_schemas", {"database": "postgres"})
    )

    assert result.is_error is False
    assert "public" in result.structured_content["result"]


def test_call_tool_propagates_validation_error_to_the_client():
    # MCPServer wraps any tool exception; the original error stays attached as
    # the cause so the client can still read the real message.
    with pytest.raises(UnexpectedToolError) as excinfo:
        asyncio.run(
            server.mcp.call_tool(
                "read_table", {"database": "postgres", "table": "x", "limit": 0}
            )
        )

    assert isinstance(excinfo.value.__cause__, ValueError)
    assert "limit must be between 1 and 1000" in str(excinfo.value.__cause__)
