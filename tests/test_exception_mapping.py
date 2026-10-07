"""Unit tests for server._handle_exception, the error translation helper."""

import logging

import psycopg
import pytest

from server import _handle_exception


@pytest.fixture(autouse=True)
def _quiet_logger(caplog):
    caplog.set_level(logging.CRITICAL)


def test_value_error_is_reraised_with_the_same_message():
    original = ValueError("limit must be between 1 and 1000")

    with pytest.raises(ValueError) as excinfo:
        _handle_exception("read_table", original)

    assert str(excinfo.value) == "limit must be between 1 and 1000"
    assert excinfo.value.__cause__ is original


@pytest.mark.parametrize(
    ("error", "expected_type", "expected_message"),
    [
        (
            psycopg.errors.UniqueViolation(),
            ValueError,
            "insert_row: a unique constraint was violated.",
        ),
        (
            psycopg.errors.ForeignKeyViolation(),
            ValueError,
            "insert_row: a foreign-key constraint was violated.",
        ),
        (
            psycopg.errors.NotNullViolation(),
            ValueError,
            "insert_row: a required column value is missing.",
        ),
        (
            psycopg.errors.CheckViolation(),
            ValueError,
            "insert_row: a database check constraint was violated.",
        ),
        (
            psycopg.errors.UndefinedTable(),
            ValueError,
            "read_table: the requested table does not exist.",
        ),
        (
            psycopg.errors.UndefinedColumn(),
            ValueError,
            "read_table: the requested column does not exist.",
        ),
        (
            psycopg.errors.InvalidCatalogName(),
            ValueError,
            "create_table: the requested database does not exist.",
        ),
        (
            psycopg.errors.InsufficientPrivilege(),
            PermissionError,
            "create_table: PostgreSQL permission denied.",
        ),
        (
            psycopg.OperationalError(),
            ConnectionError,
            "create_table: could not connect to PostgreSQL.",
        ),
        (
            psycopg.errors.SyntaxError(),
            RuntimeError,
            "query: PostgreSQL operation failed.",
        ),
        (
            psycopg.errors.DuplicateTable(),
            RuntimeError,
            "create_table: PostgreSQL operation failed.",
        ),
    ],
)
def test_postgres_errors_are_translated(error, expected_type, expected_message):
    tool_name = expected_message.split(":", 1)[0]

    with pytest.raises(expected_type) as excinfo:
        _handle_exception(tool_name, error)

    assert str(excinfo.value) == expected_message
    assert excinfo.value.__cause__ is error


def test_unknown_exception_becomes_runtime_error():
    original = KeyError("boom")

    with pytest.raises(RuntimeError) as excinfo:
        _handle_exception("query", original)

    assert str(excinfo.value) == "query: an unexpected error occurred."
    assert excinfo.value.__cause__ is original


def test_generic_psycopg_error_is_not_leaked_to_the_caller():
    original = psycopg.errors.ProgrammingError("SELECT * FROM missing")

    with pytest.raises(RuntimeError) as excinfo:
        _handle_exception("query", original)

    assert "PostgreSQL operation failed" in str(excinfo.value)
    assert excinfo.value.__cause__ is original
