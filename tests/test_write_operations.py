"""Tests for the schema and write tools (CRUD plus ALTER)."""

import pytest

import server

pytestmark = pytest.mark.requires_postgres

CUSTOMER_COLUMNS = {
    "customer_id": "INTEGER PRIMARY KEY",
    "name": "VARCHAR(100) NOT NULL",
    "email": "VARCHAR(255)",
    "phone": "VARCHAR(20)",
    "city": "VARCHAR(100)",
}


class TestCreateTable:
    def test_create_table_reports_success_and_is_visible(self, scratch_db):
        result = server.create_table(scratch_db, "customers", CUSTOMER_COLUMNS)

        assert result["status"] == "created"
        assert result["database"] == scratch_db
        assert result["schema"] == "public"
        assert result["table"] == "customers"
        assert result["columns"] == CUSTOMER_COLUMNS
        assert "created successfully" in result["message"]
        assert server.list_tables(scratch_db) == ["customers"]

    def test_create_table_rejects_empty_name(self, scratch_db):
        with pytest.raises(ValueError, match="Table name cannot be empty"):
            server.create_table(scratch_db, "", CUSTOMER_COLUMNS)

    def test_create_table_rejects_empty_columns(self, scratch_db):
        with pytest.raises(ValueError, match="columns cannot be empty"):
            server.create_table(scratch_db, "customers", {})

    @pytest.mark.parametrize("name", ["order details", "customers;--", "tbl.name"])
    def test_create_table_rejects_invalid_table_name(self, scratch_db, name):
        with pytest.raises(ValueError, match="only letters, numbers"):
            server.create_table(scratch_db, name, CUSTOMER_COLUMNS)

    def test_create_table_rejects_invalid_column_name(self, scratch_db):
        with pytest.raises(ValueError, match="Invalid column name: bad col"):
            server.create_table(scratch_db, "customers", {"bad col": "VARCHAR(10)"})

    def test_duplicate_table_raises_runtime_error(self, customers_table):
        with pytest.raises(RuntimeError, match="PostgreSQL operation failed"):
            server.create_table(customers_table, "customers", {"other": "INTEGER"})


class TestInsertRow:
    def test_insert_returns_the_stored_row(self, customers_table):
        row = server.insert_row(
            customers_table,
            "customers",
            {
                "customer_id": 1,
                "name": "John",
                "email": "john@example.com",
                "phone": "9876543210",
                "city": "Chennai",
            },
        )

        assert row == {
            "customer_id": 1,
            "name": "John",
            "email": "john@example.com",
            "phone": "9876543210",
            "city": "Chennai",
        }
        assert server.count_rows(customers_table, "customers") == 1

    def test_duplicate_primary_key_raises_value_error(self, customers_table):
        server.insert_row(
            customers_table, "customers", {"customer_id": 1, "name": "John"}
        )

        with pytest.raises(ValueError, match="a unique constraint was violated"):
            server.insert_row(
                customers_table, "customers", {"customer_id": 1, "name": "Jane"}
            )

    def test_missing_not_null_column_raises_value_error(self, customers_table):
        with pytest.raises(ValueError, match="a required column value is missing"):
            server.insert_row(customers_table, "customers", {"customer_id": 1})

    def test_unknown_column_raises_value_error(self, customers_table):
        with pytest.raises(ValueError, match="the requested column does not exist"):
            server.insert_row(
                customers_table,
                "customers",
                {"customer_id": 1, "name": "John", "nickname": "Jo"},
            )

    def test_empty_data_is_rejected(self, customers_table):
        with pytest.raises(ValueError, match="data cannot be empty"):
            server.insert_row(customers_table, "customers", {})


class TestInsertRows:
    def test_multiple_rows_are_inserted(self, customers_table):
        result = server.insert_rows(
            customers_table,
            "customers",
            [
                {"customer_id": 1, "name": "John"},
                {"customer_id": 2, "name": "Asha"},
            ],
        )

        assert result == {"inserted": 2, "table": "customers"}
        assert server.count_rows(customers_table, "customers") == 2

    def test_rows_with_different_columns_are_rejected(self, customers_table):
        with pytest.raises(ValueError, match="All rows must contain the same columns"):
            server.insert_rows(
                customers_table,
                "customers",
                [{"customer_id": 1, "name": "John"}, {"customer_id": 2}],
            )

        assert server.count_rows(customers_table, "customers") == 0

    def test_empty_row_list_is_rejected(self, customers_table):
        with pytest.raises(ValueError, match="rows cannot be empty"):
            server.insert_rows(customers_table, "customers", [])


class TestUpdateRows:
    def test_matching_row_is_updated(self, seeded_customers):
        result = server.update_rows(
            seeded_customers,
            "customers",
            {"city": "Mumbai"},
            {"customer_id": 1},
        )

        assert result == {"updated_rows": 1, "table": "customers"}
        assert server.query(
            seeded_customers, "SELECT city FROM customers WHERE customer_id = 1"
        ) == [{"city": "Mumbai"}]

    def test_non_matching_where_updates_nothing(self, seeded_customers):
        result = server.update_rows(
            seeded_customers,
            "customers",
            {"city": "Mumbai"},
            {"customer_id": 999},
        )

        assert result == {"updated_rows": 0, "table": "customers"}

    def test_empty_updates_are_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="updates cannot be empty"):
            server.update_rows(
                seeded_customers, "customers", {}, {"customer_id": 1}
            )

    def test_missing_where_is_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="Refusing to update the entire table"):
            server.update_rows(
                seeded_customers, "customers", {"city": "Mumbai"}, {}
            )

        assert server.count_rows(seeded_customers, "customers") == 3
        cities = [
            row["city"]
            for row in server.query(seeded_customers, "SELECT city FROM customers")
        ]
        assert sorted(cities) == ["Chennai", "Delhi", "Pune"]


class TestDeleteRows:
    def test_matching_rows_are_deleted(self, seeded_customers):
        result = server.delete_rows(
            seeded_customers, "customers", {"customer_id": 3}
        )

        assert result == {"deleted_rows": 1, "table": "customers"}
        assert server.count_rows(seeded_customers, "customers") == 2

    def test_non_matching_where_deletes_nothing(self, seeded_customers):
        result = server.delete_rows(
            seeded_customers, "customers", {"customer_id": 999}
        )

        assert result == {"deleted_rows": 0, "table": "customers"}
        assert server.count_rows(seeded_customers, "customers") == 3

    def test_missing_where_is_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="Refusing to delete the entire table"):
            server.delete_rows(seeded_customers, "customers", {})

        assert server.count_rows(seeded_customers, "customers") == 3

    def test_combined_where_uses_and(self, seeded_customers):
        result = server.delete_rows(
            seeded_customers,
            "customers",
            {"customer_id": 3, "city": "Chennai"},
        )

        assert result["deleted_rows"] == 0
        assert server.count_rows(seeded_customers, "customers") == 3


class TestUpsertRow:
    def test_new_conflict_key_inserts_a_row(self, customers_table):
        result = server.upsert_row(
            customers_table,
            "customers",
            {"customer_id": 9, "name": "Ups", "city": "Kochi"},
            "customer_id",
        )

        assert result["status"] == "success"
        assert result["operation"] == "upsert"
        assert result["row"]["customer_id"] == 9
        assert result["row"]["name"] == "Ups"
        assert result["row"]["city"] == "Kochi"
        # RETURNING * gives every column, including the ones not supplied
        assert result["row"]["email"] is None
        assert result["row"]["phone"] is None

    def test_existing_conflict_key_updates_the_row(self, seeded_customers):
        result = server.upsert_row(
            seeded_customers,
            "customers",
            {"customer_id": 1, "name": "John Updated", "city": "Mumbai"},
            "customer_id",
        )

        assert result["row"]["name"] == "John Updated"
        assert server.count_rows(seeded_customers, "customers") == 3
        assert server.query(
            seeded_customers,
            "SELECT city FROM customers WHERE customer_id = 1",
        ) == [{"city": "Mumbai"}]

    def test_only_conflict_column_is_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="At least one column besides"):
            server.upsert_row(
                seeded_customers, "customers", {"customer_id": 1}, "customer_id"
            )

    def test_empty_data_is_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="data cannot be empty"):
            server.upsert_row(seeded_customers, "customers", {}, "customer_id")

    def test_empty_conflict_column_is_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="conflict_column is required"):
            server.upsert_row(
                seeded_customers, "customers", {"customer_id": 1}, ""
            )


class TestAlterTable:
    def test_add_column(self, customers_table):
        result = server.alter_table(
            customers_table, "customers", "add_column", "notes", column_type="TEXT"
        )

        assert result["status"] == "success"
        assert result["operation"] == "add_column"
        assert result["column"] == "notes"
        names = [
            column["column_name"]
            for column in server.describe_table(customers_table, "customers")
        ]
        assert "notes" in names

    def test_rename_column(self, customers_table):
        server.alter_table(
            customers_table, "customers", "add_column", "notes", column_type="TEXT"
        )
        server.alter_table(
            customers_table,
            "customers",
            "rename_column",
            "notes",
            new_column="remarks",
        )

        names = [
            column["column_name"]
            for column in server.describe_table(customers_table, "customers")
        ]
        assert "remarks" in names
        assert "notes" not in names

    def test_drop_column(self, customers_table):
        server.alter_table(
            customers_table, "customers", "add_column", "notes", column_type="TEXT"
        )
        server.alter_table(customers_table, "customers", "drop_column", "notes")

        names = [
            column["column_name"]
            for column in server.describe_table(customers_table, "customers")
        ]
        assert "notes" not in names

    def test_add_column_requires_column_type(self, customers_table):
        with pytest.raises(ValueError, match="column_type is required"):
            server.alter_table(
                customers_table, "customers", "add_column", "notes"
            )

    def test_rename_requires_new_column(self, customers_table):
        with pytest.raises(ValueError, match="new_column is required"):
            server.alter_table(
                customers_table, "customers", "rename_column", "notes"
            )

    def test_unsupported_operation_is_rejected(self, customers_table):
        with pytest.raises(ValueError, match="Unsupported operation"):
            server.alter_table(
                customers_table, "customers", "truncate", "notes"
            )

    def test_empty_table_name_is_rejected(self, customers_table):
        with pytest.raises(ValueError, match="Table name cannot be empty"):
            server.alter_table(
                customers_table, "", "add_column", "notes", column_type="TEXT"
            )

    def test_empty_column_name_is_rejected(self, customers_table):
        with pytest.raises(ValueError, match="Column name cannot be empty"):
            server.alter_table(
                customers_table, "customers", "add_column", "", column_type="TEXT"
            )


class TestDeleteTable:
    def test_deleted_table_disappears(self, customers_table):
        result = server.delete_table(customers_table, "customers")

        assert result["status"] == "deleted"
        assert "deleted successfully" in result["message"]
        assert server.list_tables(customers_table) == []
        assert server.describe_table(customers_table, "customers") == []

    def test_delete_is_idempotent(self, customers_table):
        server.delete_table(customers_table, "customers")

        assert server.delete_table(customers_table, "customers")["status"] == "deleted"

    def test_empty_table_name_is_rejected(self, customers_table):
        with pytest.raises(ValueError, match="Table name cannot be empty"):
            server.delete_table(customers_table, "")
