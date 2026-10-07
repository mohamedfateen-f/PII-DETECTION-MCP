"""Tests for the database discovery tools (create/list/delete/info)."""

import uuid

import pytest

import server

pytestmark = pytest.mark.requires_postgres


class TestListDatabases:
    def test_postgres_database_is_listed(self):
        assert "postgres" in server.list_databases()

    def test_listed_names_are_sorted_and_unique(self):
        names = server.list_databases()

        assert names == sorted(names)
        assert len(names) == len(set(names))


class TestCreateDatabase:
    def test_created_database_appears_in_listing(self, scratch_db):
        assert scratch_db in server.list_databases()

    def test_second_create_reports_already_exists(self, scratch_db):
        result = server.create_database(scratch_db)

        assert result == {
            "status": "already_exists",
            "database": scratch_db,
            "message": f"Database '{scratch_db}' already exists.",
        }

    def test_create_rejects_empty_name(self):
        with pytest.raises(ValueError, match="Database name cannot be empty"):
            server.create_database("")

    def test_create_rejects_invalid_characters(self):
        with pytest.raises(ValueError, match="only letters, numbers"):
            server.create_database("my-db")

    def test_fresh_database_is_created_end_to_end(self):
        name = "pytest_tmp_" + uuid.uuid4().hex[:10]

        try:
            result = server.create_database(name)

            assert result["status"] == "created"
            assert name in server.list_databases()
        finally:
            server.delete_database(name)


class TestDeleteDatabase:
    def test_delete_refuses_postgres(self):
        with pytest.raises(ValueError, match="not allowed"):
            server.delete_database("postgres")

    def test_delete_reports_missing_database(self):
        missing = "pytest_missing_" + uuid.uuid4().hex[:8]

        result = server.delete_database(missing)

        assert result == {
            "status": "not_found",
            "database": missing,
            "message": f"Database '{missing}' does not exist.",
        }

    def test_delete_removes_database_from_listing(self, scratch_db):
        result = server.delete_database(scratch_db)

        assert result["status"] == "deleted"
        assert scratch_db not in server.list_databases()

    def test_delete_rejects_empty_name(self):
        with pytest.raises(ValueError, match="Database name cannot be empty"):
            server.delete_database("")


class TestDatabaseInfo:
    def test_info_describes_the_requested_database(self, scratch_db):
        info = server.database_info(scratch_db)

        assert info["database"] == scratch_db
        assert info["user"]
        assert info["version"].startswith("PostgreSQL")

    def test_info_for_missing_database_raises_connection_error(self):
        missing = "pytest_missing_" + uuid.uuid4().hex[:8]

        with pytest.raises(ConnectionError, match="could not connect"):
            server.database_info(missing)
