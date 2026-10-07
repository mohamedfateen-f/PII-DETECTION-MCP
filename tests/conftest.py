"""Shared fixtures for the PostgreSQL MCP backend test suite.

Every database test runs against a throwaway database that is created before
the test and dropped afterwards, so no pre-existing data is touched.
"""

import logging
import sys
import uuid
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import server  # noqa: E402
from database import get_connection  # noqa: E402

# server.py logs a rich traceback for every handled error. Silence that logger
# so the pytest output stays readable - the tests assert on the raised
# exceptions, not on the log records.
_server_logger = logging.getLogger("server")
_server_logger.propagate = False
_server_logger.addHandler(logging.NullHandler())


def _postgres_reachable() -> bool:
    """Return True when the credentials in .env reach a PostgreSQL server."""

    try:
        with get_connection("postgres") as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False


POSTGRES_AVAILABLE = _postgres_reachable()


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        "requires_postgres: needs a PostgreSQL server reachable with the "
        "credentials in .env",
    )


def pytest_collection_modifyitems(config, items) -> None:
    if POSTGRES_AVAILABLE:
        return

    skip = pytest.mark.skip(
        reason="PostgreSQL is not reachable with the credentials in .env"
    )

    for item in items:
        if "requires_postgres" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def scratch_db() -> str:
    """Create a unique scratch database and drop it again on teardown."""

    name = "pytest_tmp_" + uuid.uuid4().hex[:10]
    server.create_database(name)

    try:
        yield name
    finally:
        try:
            server.delete_database(name)
        except Exception:
            pass


@pytest.fixture
def customers_table(scratch_db: str) -> str:
    """Create the table used by the read/write tests in a scratch database."""

    server.create_table(
        scratch_db,
        "customers",
        {
            "customer_id": "INTEGER PRIMARY KEY",
            "name": "VARCHAR(100) NOT NULL",
            "email": "VARCHAR(255)",
            "phone": "VARCHAR(20)",
            "city": "VARCHAR(100)",
        },
    )

    return scratch_db


@pytest.fixture
def seeded_customers(customers_table: str) -> str:
    """Same as ``customers_table`` but with three rows already inserted."""

    server.insert_rows(
        customers_table,
        "customers",
        [
            {
                "customer_id": 1,
                "name": "John",
                "email": "john@example.com",
                "phone": "9876543210",
                "city": "Chennai",
            },
            {
                "customer_id": 2,
                "name": "Asha",
                "email": "asha@example.com",
                "phone": "9876543211",
                "city": "Delhi",
            },
            {
                "customer_id": 3,
                "name": "Varun",
                "email": "varun@example.com",
                "phone": "9876543212",
                "city": "Pune",
            },
        ],
    )

    return customers_table
