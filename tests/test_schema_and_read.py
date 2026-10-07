"""Tests for schema discovery and the read-only query tools."""

import pytest

import server

pytestmark = pytest.mark.requires_postgres


class TestSchemaDiscovery:
    def test_public_schema_is_listed(self, scratch_db):
        assert "public" in server.list_schemas(scratch_db)

    def test_system_schemas_are_excluded(self, scratch_db):
        schemas = server.list_schemas(scratch_db)

        assert "pg_catalog" not in schemas
        assert "information_schema" not in schemas

    def test_new_database_has_no_tables(self, scratch_db):
        assert server.list_tables(scratch_db) == []

    def test_created_table_is_listed(self, customers_table):
        assert server.list_tables(customers_table) == ["customers"]

    def test_unknown_schema_returns_empty_list(self, customers_table):
        assert server.list_tables(customers_table, schema="reporting") == []

    def test_describe_table_returns_ordered_column_metadata(self, customers_table):
        columns = server.describe_table(customers_table, "customers")

        assert [column["column_name"] for column in columns] == [
            "customer_id",
            "name",
            "email",
            "phone",
            "city",
        ]
        assert columns[0] == {
            "column_name": "customer_id",
            "data_type": "integer",
            "nullable": "NO",
            "default": None,
        }
        assert columns[1]["data_type"] == "character varying"
        assert columns[1]["nullable"] == "NO"

    def test_describe_missing_table_returns_empty_list(self, customers_table):
        assert server.describe_table(customers_table, "missing_table") == []


class TestReadTable:
    def test_rows_are_returned_as_dictionaries(self, seeded_customers):
        rows = server.read_table(seeded_customers, "customers")

        assert len(rows) == 3
        assert rows[0] == {
            "customer_id": 1,
            "name": "John",
            "email": "john@example.com",
            "phone": "9876543210",
            "city": "Chennai",
        }

    def test_limit_is_applied(self, seeded_customers):
        assert len(server.read_table(seeded_customers, "customers", limit=2)) == 2

    @pytest.mark.parametrize("limit", [0, -5, 1001])
    def test_limit_outside_range_is_rejected(self, seeded_customers, limit):
        with pytest.raises(ValueError, match="limit must be between 1 and 1000"):
            server.read_table(seeded_customers, "customers", limit=limit)

    def test_missing_table_raises_value_error(self, customers_table):
        with pytest.raises(ValueError, match="the requested table does not exist"):
            server.read_table(customers_table, "missing_table")

    def test_table_name_is_treated_as_an_identifier(self, seeded_customers):
        hostile_name = "customers; DROP TABLE customers--"

        with pytest.raises(ValueError, match="does not exist"):
            server.read_table(seeded_customers, table=hostile_name)

        assert server.count_rows(seeded_customers, "customers") == 3


class TestQuery:
    def test_select_returns_list_of_dictionaries(self, seeded_customers):
        rows = server.query(
            seeded_customers, "SELECT name FROM customers ORDER BY customer_id"
        )

        assert rows == [{"name": "John"}, {"name": "Asha"}, {"name": "Varun"}]

    def test_lowercase_select_is_allowed(self, seeded_customers):
        rows = server.query(
            seeded_customers, "select count(*) as total from customers"
        )

        assert rows == [{"total": 3}]

    @pytest.mark.parametrize(
        "statement",
        [
            "DELETE FROM customers",
            "delete from customers",
            "UPDATE customers SET city = 'X'",
            "  DROP TABLE customers",
            "INSERT INTO customers (customer_id) VALUES (99)",
        ],
    )
    def test_non_select_statements_are_rejected(
        self, seeded_customers, statement
    ):
        with pytest.raises(ValueError, match="Only SELECT queries are allowed"):
            server.query(seeded_customers, statement)

        # the rejected statement had no effect
        assert server.count_rows(seeded_customers, "customers") == 3

    def test_invalid_sql_raises_runtime_error(self, customers_table):
        with pytest.raises(RuntimeError, match="PostgreSQL operation failed"):
            server.query(customers_table, "SELECT * FROM")

    def test_unknown_column_raises_value_error(self, customers_table):
        with pytest.raises(ValueError, match="the requested column does not exist"):
            server.query(customers_table, "SELECT nope FROM customers")


class TestStatistics:
    def test_count_rows_matches_inserted_rows(self, seeded_customers):
        assert server.count_rows(seeded_customers, "customers") == 3

    def test_count_rows_on_empty_table_is_zero(self, customers_table):
        assert server.count_rows(customers_table, "customers") == 0

    def test_count_rows_missing_table_raises_value_error(self, customers_table):
        with pytest.raises(ValueError, match="the requested table does not exist"):
            server.count_rows(customers_table, "missing_table")

    def test_table_stats_reports_row_count(self, seeded_customers):
        stats = server.table_stats(seeded_customers, "customers")

        assert stats == {
            "database": seeded_customers,
            "schema": "public",
            "table": "customers",
            "row_count": 3,
        }
