"""Tests for the PII-aware (anonymizing) write tools."""

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


class TestAnonymizeAndInsert:
    def test_stored_row_contains_masked_values_only(self, customers_table):
        result = server.anonymize_and_insert(
            customers_table,
            "customers",
            {
                "customer_id": 1,
                "name": "Neha",
                "email": "neha@example.com",
                "phone": "9876543210",
                "city": "Chennai",
            },
        )

        assert result["status"] == "success"
        assert "anonymized and inserted" in result["message"]
        assert result["anonymized_data"] == {
            "customer_id": 1,
            "name": "Neha",
            "email": "n***@example.com",
            "phone": "******3210",
            "city": "Chennai",
        }
        assert result["inserted_row"] == result["anonymized_data"]

        stored = server.query(
            customers_table, "SELECT email, phone FROM customers"
        )
        assert stored == [{"email": "n***@example.com", "phone": "******3210"}]

    def test_non_sensitive_columns_are_kept_verbatim(self, customers_table):
        result = server.anonymize_and_insert(
            customers_table,
            "customers",
            {"customer_id": 2, "name": "Mohamed Fateen", "city": "Chennai"},
        )

        assert result["inserted_row"]["name"] == "Mohamed Fateen"
        assert result["inserted_row"]["city"] == "Chennai"
        assert result["inserted_row"]["customer_id"] == 2

    def test_empty_data_is_rejected(self, customers_table):
        with pytest.raises(ValueError, match="data cannot be empty"):
            server.anonymize_and_insert(customers_table, "customers", {})


class TestAnonymizeAndInsertRows:
    def test_every_row_is_masked_before_insert(self, customers_table):
        result = server.anonymize_and_insert_rows(
            customers_table,
            "customers",
            [
                {
                    "customer_id": 1,
                    "name": "X",
                    "email": "x@example.com",
                    "phone": "9876543211",
                },
                {
                    "customer_id": 2,
                    "name": "Y",
                    "email": "y@example.com",
                    "phone": "9876543212",
                },
            ],
        )

        assert result["status"] == "success"
        assert result["inserted"] == 2
        assert "anonymized before database insertion" in result["message"]
        assert server.count_rows(customers_table, "customers") == 2

        stored = server.query(
            customers_table, "SELECT email FROM customers ORDER BY customer_id"
        )
        assert stored == [
            {"email": "*@example.com"},
            {"email": "*@example.com"},
        ]

    def test_empty_row_list_is_rejected(self, customers_table):
        with pytest.raises(ValueError, match="rows cannot be empty"):
            server.anonymize_and_insert_rows(customers_table, "customers", [])

    def test_rows_with_different_columns_are_rejected(self, customers_table):
        with pytest.raises(ValueError, match="All rows must contain the same columns"):
            server.anonymize_and_insert_rows(
                customers_table,
                "customers",
                [{"customer_id": 1, "name": "X"}, {"customer_id": 2}],
            )

        assert server.count_rows(customers_table, "customers") == 0


class TestAnonymizedUpdate:
    def test_update_values_are_masked(self, seeded_customers):
        result = server.anonymized_update(
            seeded_customers,
            "customers",
            {"email": "new@example.com"},
            {"customer_id": 1},
        )

        assert result["status"] == "success"
        assert result["updated_rows"] == 1
        assert result["anonymized_updates"] == {"email": "n**@example.com"}
        assert server.query(
            seeded_customers, "SELECT email FROM customers WHERE customer_id = 1"
        ) == [{"email": "n**@example.com"}]

    def test_where_values_are_used_verbatim(self, seeded_customers):
        # The WHERE clause is not anonymized, so a raw PII value still matches
        # a row that was inserted with raw PII.
        server.insert_row(
            seeded_customers,
            "customers",
            {"customer_id": 4, "name": "Raw", "email": "raw@example.com"},
        )

        result = server.anonymized_update(
            seeded_customers,
            "customers",
            {"city": "Mumbai"},
            {"email": "raw@example.com"},
        )

        assert result["updated_rows"] == 1
        assert server.query(
            seeded_customers, "SELECT city FROM customers WHERE customer_id = 4"
        ) == [{"city": "Mumbai"}]

    def test_empty_updates_are_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="updates cannot be empty"):
            server.anonymized_update(
                seeded_customers, "customers", {}, {"customer_id": 1}
            )

    def test_missing_where_is_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="Refusing to update the entire table"):
            server.anonymized_update(
                seeded_customers, "customers", {"city": "Mumbai"}, {}
            )

        assert server.count_rows(seeded_customers, "customers") == 3


class TestAnonymizedDelete:
    def test_matching_rows_are_deleted(self, seeded_customers):
        result = server.anonymized_delete(
            seeded_customers, "customers", {"customer_id": 2}
        )

        assert result == {
            "status": "success",
            "table": "customers",
            "deleted_rows": 1,
        }
        assert server.count_rows(seeded_customers, "customers") == 2

    def test_missing_where_is_rejected(self, seeded_customers):
        with pytest.raises(ValueError, match="Refusing to delete the entire table"):
            server.anonymized_delete(seeded_customers, "customers", {})

        assert server.count_rows(seeded_customers, "customers") == 3


class TestUpsertAnonymizeFlag:
    def test_anonymize_flag_masks_stored_pii(self, customers_table):
        server.upsert_row(
            customers_table,
            "customers",
            {"customer_id": 1, "name": "Raw", "email": "raw@example.com"},
            "customer_id",
            anonymize=True,
        )

        assert server.query(
            customers_table, "SELECT email FROM customers"
        ) == [{"email": "r**@example.com"}]

    def test_pii_is_stored_verbatim_without_the_flag(self, customers_table):
        server.upsert_row(
            customers_table,
            "customers",
            {"customer_id": 1, "name": "Raw", "email": "raw@example.com"},
            "customer_id",
        )

        assert server.query(
            customers_table, "SELECT email FROM customers"
        ) == [{"email": "raw@example.com"}]
