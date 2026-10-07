# Test Case Output — PostgreSQL MCP Backend

All numbers, outputs and error messages in this document come from a real
`pytest` run performed on the machine described below. Nothing here is
estimated or hand-written.

## 1. Run details

| Item | Value |
| --- | --- |
| Command | `uv run pytest` |
| Working directory | `C:\Users\DELL\Desktop\Projects\Context layer and MCP\backend` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options] testpaths = ["tests"]`) |
| Platform | `win32` — Python 3.14.7, pytest 9.1.1, pluggy 1.6.0 |
| Project deps | `mcp 2.2.0`, `psycopg 3.3.6`, `python-dotenv 1.2.3` |
| Database under test | PostgreSQL 17.11 on x86_64-windows, `localhost:5432`, user `postgres` (credentials from `.env`) |
| Test files | 8 (`tests/conftest.py` + 7 test modules) |
| Collected / executed | 146 |
| Result | **146 passed, 0 failed, 0 errors, 0 skipped in 112.58s (0:01:52)** |

Actual terminal output of the recorded run:

```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\DELL\Desktop\Projects\Context layer and MCP\backend
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1
collected 146 items

tests\test_anonymization_tools.py ..............                         [  9%]
tests\test_database_discovery.py .............                           [ 18%]
tests\test_exception_mapping.py ..............                           [ 28%]
tests\test_mcp_registration.py ......                                    [ 32%]
tests\test_pii_anonymizer.py ................................            [ 54%]
tests\test_schema_and_read.py ...........................                [ 72%]
tests\test_write_operations.py ........................................ [100%]

======================= 146 passed in 112.58s (0:01:52) =======================
```

Summary per module:

| Test module | Tests | Passed | Failed |
| --- | ---: | ---: | ---: |
| `tests/test_pii_anonymizer.py` | 32 | 32 | 0 |
| `tests/test_exception_mapping.py` | 14 | 14 | 0 |
| `tests/test_mcp_registration.py` | 6 | 6 | 0 |
| `tests/test_database_discovery.py` | 13 | 13 | 0 |
| `tests/test_schema_and_read.py` | 27 | 27 | 0 |
| `tests/test_write_operations.py` | 40 | 40 | 0 |
| `tests/test_anonymization_tools.py` | 14 | 14 | 0 |
| **Total** | **146** | **146** | **0** |

## 2. How the tests are organised

* `tests/conftest.py` puts `src/` on `sys.path`, silences the traceback
  logging of `server.py`, and provides the fixtures:
  * `scratch_db` — creates a unique database `pytest_tmp_<10 hex>` before each
    test and drops it afterwards (verified: no `pytest_*` databases remain
    after the run),
  * `customers_table` — that scratch database plus a `customers` table
    (`customer_id INTEGER PRIMARY KEY`, `name VARCHAR(100) NOT NULL`,
    `email`, `phone`, `city`),
  * `seeded_customers` — the same table with three inserted rows.
* Tests that need a live server are marked `requires_postgres`; they are
  skipped automatically if the server cannot be reached (none were skipped in
  this run).
* Pure-unit tests (PII anonymizer, exception mapping) do not touch the
  database.

Reproduce with:

```powershell
uv run pytest                 # full suite
uv run pytest -v              # one line per test case
uv run pytest tests/test_pii_anonymizer.py
```

---

## 3. Test cases — `tests/test_pii_anonymizer.py` (32)

| # | Test case | What it verifies | Result |
| --- | --- | --- | --- |
| TC-001 | `TestPatterns::test_six_pii_patterns_are_registered` | `PII_PATTERNS` contains exactly EMAIL, PHONE, PAN, AADHAAR, CREDIT_CARD, IP_ADDRESS | PASS |
| TC-002 | `TestPatterns::test_sensitive_column_set_matches_documentation` | `SENSITIVE_COLUMNS` equals the documented six column names | PASS |
| TC-003 | `TestPatterns::test_email_pattern_matches` | Email regex matches `john.doe@example.com` inside a sentence | PASS |
| TC-004 | `TestPatterns::test_phone_pattern_matches_indian_numbers` | Phone regex matches `9876543210`, `+91 9876543210`, `+91-9876543210` | PASS |
| TC-005 | `TestPatterns::test_phone_pattern_misses_country_code_without_separator` | `+919876543210` is **not** matched (no separator after `+91`) | PASS |
| TC-006 | `TestPatterns::test_pan_pattern_requires_uppercase_shape` | `ABCDE1234F` matched, `abcde1234f` not matched | PASS |
| TC-007 | `TestPatterns::test_aadhaar_pattern_requires_separators` | `1234-5678-9012` and `1234 5678 9012` matched; `123456789012` not matched | PASS |
| TC-008 | `TestPatterns::test_credit_card_pattern_matches_spaced_and_hyphenated` | 16 digits with `-` or spaces matched | PASS |
| TC-009 | `TestPatterns::test_ip_pattern_matches_ipv4_shape` | IPv4 shape `192.168.1.100` matched | PASS |
| TC-010 | `TestMaskValue::test_email_masks_username_keeps_domain` | `john@example.com` → `j***@example.com` | PASS |
| TC-011 | `TestMaskValue::test_email_with_short_username_is_fully_masked` | `ab@x.com` → `**@x.com` | PASS |
| TC-012 | `TestMaskValue::test_phone_keeps_last_four_digits` | `9876543210` → `******3210` | PASS |
| TC-013 | `TestMaskValue::test_phone_with_country_code_keeps_last_four_digits` | `+91 9876543210` → `********3210` (country code digits are masked too) | PASS |
| TC-014 | `TestMaskValue::test_pan_keeps_last_four_characters` | `ABCDE1234F` → `*****234F` | PASS |
| TC-015 | `TestMaskValue::test_aadhaar_keeps_last_four_digits` | `1234-5678-9012` / `1234 5678 9012` → `XXXX XXXX 9012` | PASS |
| TC-016 | `TestMaskValue::test_credit_card_keeps_last_four_digits` | `1234-5678-9012-3456` → `**** **** **** 3456` | PASS |
| TC-017 | `TestMaskValue::test_ip_address_masks_last_two_octets` | `192.168.1.100` → `192.168.XXX.XXX` | PASS |
| TC-018 | `TestMaskValue::test_unknown_pii_type_is_masked_with_asterisks` | Unknown type falls back to `*` × length | PASS |
| TC-019 | `TestAnonymizeText::test_masks_multiple_values_in_one_string` | `Contact john@example.com or 9876543210` → `Contact j***@example.com or ******3210` | PASS |
| TC-020 | `TestAnonymizeText::test_masks_mixed_pii_types_right_to_left` | Aadhaar + credit card in one string masked correctly (offsets stay valid) | PASS |
| TC-021 | `TestAnonymizeText::test_none_is_returned_unchanged` | `anonymize_text(None)` returns `None` | PASS |
| TC-022 | `TestAnonymizeText::test_non_string_values_are_stringified` | `anonymize_text(123)` returns `"123"` | PASS |
| TC-023 | `TestAnonymizeText::test_text_without_pii_is_returned_unchanged` | Plain text passes through | PASS |
| TC-024 | `TestAnonymizeText::test_country_code_prefix_survives_masking` | `+91 9876543210` → `+91 ******3210` (prefix not part of the match) | PASS |
| TC-025 | `TestAnonymizeText::test_lowercase_pan_is_left_unchanged` | Lowercase PAN is not detected | PASS |
| TC-026 | `TestAnonymizeText::test_unseparated_aadhaar_is_left_unchanged` | 12 digits without separators are not detected as Aadhaar | PASS |
| TC-027 | `TestAnonymizeText::test_ip_octets_are_not_validated` | `999.999.999.999` → `999.999.XXX.XXX` (no 0–255 check) | PASS |
| TC-028 | `TestAnonymizeData::test_sensitive_columns_are_masked_and_others_kept` | Full record: `Email/Phone/PAN/Aadhaar` masked, `Customer_ID/Name/City` unchanged | PASS |
| TC-029 | `TestAnonymizeData::test_column_names_are_matched_case_insensitively` | `EMAIL`, `Phone`, `Ip_Address` keys are recognised | PASS |
| TC-030 | `TestAnonymizeData::test_non_sensitive_column_keeps_pii_shaped_value` | `notes` containing an email is left untouched (column-driven design) | PASS |
| TC-031 | `TestAnonymizeData::test_original_dict_is_not_mutated` | Input dictionary is not modified in place | PASS |
| TC-032 | `TestAnonymizeData::test_input_keys_are_preserved_in_order` | Output keeps the input key order | PASS |

---

## 4. Test cases — `tests/test_exception_mapping.py` (14)

Unit tests for `server._handle_exception`; every case also asserts that the
original exception is kept as `__cause__`.

| # | Test case | What it verifies | Result |
| --- | --- | --- | --- |
| TC-033 | `test_value_error_is_reraised_with_the_same_message` | `ValueError` passes through unchanged | PASS |
| TC-034 | `test_postgres_errors_are_translated[UniqueViolation]` | → `ValueError: insert_row: a unique constraint was violated.` | PASS |
| TC-035 | `test_postgres_errors_are_translated[ForeignKeyViolation]` | → `ValueError: ...a foreign-key constraint was violated.` | PASS |
| TC-036 | `test_postgres_errors_are_translated[NotNullViolation]` | → `ValueError: ...a required column value is missing.` | PASS |
| TC-037 | `test_postgres_errors_are_translated[CheckViolation]` | → `ValueError: ...a database check constraint was violated.` | PASS |
| TC-038 | `test_postgres_errors_are_translated[UndefinedTable]` | → `ValueError: read_table: the requested table does not exist.` | PASS |
| TC-039 | `test_postgres_errors_are_translated[UndefinedColumn]` | → `ValueError: read_table: the requested column does not exist.` | PASS |
| TC-040 | `test_postgres_errors_are_translated[InvalidCatalogName]` | → `ValueError: create_table: the requested database does not exist.` | PASS |
| TC-041 | `test_postgres_errors_are_translated[InsufficientPrivilege]` | → `PermissionError: create_table: PostgreSQL permission denied.` | PASS |
| TC-042 | `test_postgres_errors_are_translated[OperationalError]` | → `ConnectionError: create_table: could not connect to PostgreSQL.` | PASS |
| TC-043 | `test_postgres_errors_are_translated[SyntaxError]` | → `RuntimeError: query: PostgreSQL operation failed.` | PASS |
| TC-044 | `test_postgres_errors_are_translated[DuplicateTable]` | → `RuntimeError: create_table: PostgreSQL operation failed.` (no dedicated mapping) | PASS |
| TC-045 | `test_unknown_exception_becomes_runtime_error` | Any other exception → `RuntimeError: ...an unexpected error occurred.` | PASS |
| TC-046 | `test_generic_psycopg_error_is_not_leaked_to_the_caller` | Generic `psycopg` error → `RuntimeError: PostgreSQL operation failed.` | PASS |

---

## 5. Test cases — `tests/test_mcp_registration.py` (6)

Exercises the MCP layer itself (`mcp.list_tools()` / `mcp.call_tool()`).

| # | Test case | What it verifies | Result |
| --- | --- | --- | --- |
| TC-047 | `test_all_expected_tools_are_registered` | Exactly 23 tools are registered, in the expected order | PASS |
| TC-048 | `test_every_tool_exposes_a_description` | Every tool has a non-empty description | PASS |
| TC-049 | `test_query_tool_schema_requires_database_and_sql` | `query` JSON schema requires `database` and `sql_query` | PASS |
| TC-050 | `test_list_tables_schema_has_default_schema_argument` | `schema` defaults to `public` and is not required | PASS |
| TC-051 | `test_call_tool_returns_structured_result` | Protocol call `list_schemas(postgres)` → `is_error=False`, `public` in `structured_content` | PASS |
| TC-052 | `test_call_tool_propagates_validation_error_to_the_client` | Protocol call with `limit=0` raises `UnexpectedToolError` whose cause is `ValueError: limit must be between 1 and 1000` | PASS |

---

## 6. Test cases — `tests/test_database_discovery.py` (13)

| # | Test case | What it verifies | Result |
| --- | --- | --- | --- |
| TC-053 | `TestListDatabases::test_postgres_database_is_listed` | `postgres` appears in `list_databases()` | PASS |
| TC-054 | `TestListDatabases::test_listed_names_are_sorted_and_unique` | Returned names are sorted and unique | PASS |
| TC-055 | `TestCreateDatabase::test_created_database_appears_in_listing` | The fixture-created database is listed | PASS |
| TC-056 | `TestCreateDatabase::test_second_create_reports_already_exists` | Second call returns `status="already_exists"` with message | PASS |
| TC-057 | `TestCreateDatabase::test_create_rejects_empty_name` | `ValueError: Database name cannot be empty.` | PASS |
| TC-058 | `TestCreateDatabase::test_create_rejects_invalid_characters` | `my-db` → `ValueError: Database name can contain only letters, numbers, and underscores.` | PASS |
| TC-059 | `TestCreateDatabase::test_fresh_database_is_created_end_to_end` | Create → listed → deleted again | PASS |
| TC-060 | `TestDeleteDatabase::test_delete_refuses_postgres` | `ValueError: Deleting the postgres database is not allowed.` | PASS |
| TC-061 | `TestDeleteDatabase::test_delete_reports_missing_database` | Missing DB → `status="not_found"` | PASS |
| TC-062 | `TestDeleteDatabase::test_delete_removes_database_from_listing` | `status="deleted"` and name disappears from the listing | PASS |
| TC-063 | `TestDeleteDatabase::test_delete_rejects_empty_name` | `ValueError: Database name cannot be empty.` | PASS |
| TC-064 | `TestDatabaseInfo::test_info_describes_the_requested_database` | `database`, `user`, `version` (starts with `PostgreSQL`) are returned | PASS |
| TC-065 | `TestDatabaseInfo::test_info_for_missing_database_raises_connection_error` | Missing DB → `ConnectionError: ...could not connect to PostgreSQL.` | PASS |

---

## 7. Test cases — `tests/test_schema_and_read.py` (27)

| # | Test case | What it verifies | Result |
| --- | --- | --- | --- |
| TC-066 | `TestSchemaDiscovery::test_public_schema_is_listed` | `public` in `list_schemas()` | PASS |
| TC-067 | `TestSchemaDiscovery::test_system_schemas_are_excluded` | `pg_catalog` / `information_schema` excluded | PASS |
| TC-068 | `TestSchemaDiscovery::test_new_database_has_no_tables` | Fresh database → `[]` | PASS |
| TC-069 | `TestSchemaDiscovery::test_created_table_is_listed` | `list_tables()` → `['customers']` | PASS |
| TC-070 | `TestSchemaDiscovery::test_unknown_schema_returns_empty_list` | Unknown schema → `[]` (no error) | PASS |
| TC-071 | `TestSchemaDiscovery::test_describe_table_returns_ordered_column_metadata` | Columns in ordinal order with `data_type`, `nullable`, `default` (`customer_id`: integer / NO / None) | PASS |
| TC-072 | `TestSchemaDiscovery::test_describe_missing_table_returns_empty_list` | Unknown table → `[]` | PASS |
| TC-073 | `TestReadTable::test_rows_are_returned_as_dictionaries` | 3 rows, keyed by column name, first row exact match | PASS |
| TC-074 | `TestReadTable::test_limit_is_applied` | `limit=2` returns 2 rows | PASS |
| TC-075 | `TestReadTable::test_limit_outside_range_is_rejected[0]` | `ValueError: limit must be between 1 and 1000` | PASS |
| TC-076 | `TestReadTable::test_limit_outside_range_is_rejected[-5]` | Same validation for negative limits | PASS |
| TC-077 | `TestReadTable::test_limit_outside_range_is_rejected[1001]` | Same validation above 1000 | PASS |
| TC-078 | `TestReadTable::test_missing_table_raises_value_error` | `ValueError: ...the requested table does not exist.` | PASS |
| TC-079 | `TestReadTable::test_table_name_is_treated_as_an_identifier` | `customers; DROP TABLE customers--` fails safely and the table still holds 3 rows | PASS |
| TC-080 | `TestQuery::test_select_returns_list_of_dictionaries` | `SELECT name ... ORDER BY` → `[{'name': 'John'}, ...]` | PASS |
| TC-081 | `TestQuery::test_lowercase_select_is_allowed` | `select count(*) as total ...` → `[{'total': 3}]` | PASS |
| TC-082 | `TestQuery::test_non_select_statements_are_rejected[DELETE FROM customers]` | `ValueError: Only SELECT queries are allowed.` + no rows deleted | PASS |
| TC-083 | `TestQuery::test_non_select_statements_are_rejected[delete from customers]` | Lowercase `delete` also rejected | PASS |
| TC-084 | `TestQuery::test_non_select_statements_are_rejected[UPDATE customers SET city = 'X']` | `UPDATE` rejected | PASS |
| TC-085 | `TestQuery::test_non_select_statements_are_rejected[  DROP TABLE customers]` | Leading whitespace + `DROP` rejected | PASS |
| TC-086 | `TestQuery::test_non_select_statements_are_rejected[INSERT INTO customers (customer_id) VALUES (99)]` | `INSERT` rejected | PASS |
| TC-087 | `TestQuery::test_invalid_sql_raises_runtime_error` | `SELECT * FROM` → `RuntimeError: query: PostgreSQL operation failed.` | PASS |
| TC-088 | `TestQuery::test_unknown_column_raises_value_error` | Unknown column → `ValueError: ...the requested column does not exist.` | PASS |
| TC-089 | `TestStatistics::test_count_rows_matches_inserted_rows` | `count_rows` = 3 after 3 inserts | PASS |
| TC-090 | `TestStatistics::test_count_rows_on_empty_table_is_zero` | Empty table → 0 | PASS |
| TC-091 | `TestStatistics::test_count_rows_missing_table_raises_value_error` | Missing table → `ValueError` | PASS |
| TC-092 | `TestStatistics::test_table_stats_reports_row_count` | `table_stats` returns database/schema/table/`row_count: 3` | PASS |

---

## 8. Test cases — `tests/test_write_operations.py` (40)

| # | Test case | What it verifies | Result |
| --- | --- | --- | --- |
| TC-093 | `TestCreateTable::test_create_table_reports_success_and_is_visible` | `status/database/schema/table/columns/message` + table listed | PASS |
| TC-094 | `TestCreateTable::test_create_table_rejects_empty_name` | `ValueError: Table name cannot be empty.` | PASS |
| TC-095 | `TestCreateTable::test_create_table_rejects_empty_columns` | `ValueError: columns cannot be empty.` | PASS |
| TC-096 | `TestCreateTable::test_create_table_rejects_invalid_table_name[order details]` | `ValueError: Table name can contain only letters, numbers, and underscores.` | PASS |
| TC-097 | `TestCreateTable::test_create_table_rejects_invalid_table_name[customers;--]` | Same validation | PASS |
| TC-098 | `TestCreateTable::test_create_table_rejects_invalid_table_name[tbl.name]` | Same validation | PASS |
| TC-099 | `TestCreateTable::test_create_table_rejects_invalid_column_name` | `ValueError: Invalid column name: bad col` | PASS |
| TC-100 | `TestCreateTable::test_duplicate_table_raises_runtime_error` | Duplicate table → `RuntimeError: create_table: PostgreSQL operation failed.` | PASS |
| TC-101 | `TestInsertRow::test_insert_returns_the_stored_row` | `RETURNING *` row matches the input, `count_rows` = 1 | PASS |
| TC-102 | `TestInsertRow::test_duplicate_primary_key_raises_value_error` | `ValueError: insert_row: a unique constraint was violated.` | PASS |
| TC-103 | `TestInsertRow::test_missing_not_null_column_raises_value_error` | `ValueError: insert_row: a required column value is missing.` | PASS |
| TC-104 | `TestInsertRow::test_unknown_column_raises_value_error` | `ValueError: ...the requested column does not exist.` | PASS |
| TC-105 | `TestInsertRow::test_empty_data_is_rejected` | `ValueError: data cannot be empty` | PASS |
| TC-106 | `TestInsertRows::test_multiple_rows_are_inserted` | `{'inserted': 2, 'table': 'customers'}` + count = 2 | PASS |
| TC-107 | `TestInsertRows::test_rows_with_different_columns_are_rejected` | `ValueError: All rows must contain the same columns.` and nothing inserted | PASS |
| TC-108 | `TestInsertRows::test_empty_row_list_is_rejected` | `ValueError: rows cannot be empty` | PASS |
| TC-109 | `TestUpdateRows::test_matching_row_is_updated` | `{'updated_rows': 1}` + stored value verified with `query` | PASS |
| TC-110 | `TestUpdateRows::test_non_matching_where_updates_nothing` | `{'updated_rows': 0}` | PASS |
| TC-111 | `TestUpdateRows::test_empty_updates_are_rejected` | `ValueError: updates cannot be empty` | PASS |
| TC-112 | `TestUpdateRows::test_missing_where_is_rejected` | `ValueError: ...Refusing to update the entire table.` and no row changed | PASS |
| TC-113 | `TestDeleteRows::test_matching_rows_are_deleted` | `{'deleted_rows': 1}` + count drops to 2 | PASS |
| TC-114 | `TestDeleteRows::test_non_matching_where_deletes_nothing` | `{'deleted_rows': 0}`, count stays 3 | PASS |
| TC-115 | `TestDeleteRows::test_missing_where_is_rejected` | `ValueError: ...Refusing to delete the entire table.` | PASS |
| TC-116 | `TestDeleteRows::test_combined_where_uses_and` | Two conditions are combined with `AND` (0 rows deleted) | PASS |
| TC-117 | `TestUpsertRow::test_new_conflict_key_inserts_a_row` | Insert path: `operation="upsert"`, `RETURNING *` includes unsupplied columns as `None` | PASS |
| TC-118 | `TestUpsertRow::test_existing_conflict_key_updates_the_row` | Update path: name/city replaced, row count unchanged | PASS |
| TC-119 | `TestUpsertRow::test_only_conflict_column_is_rejected` | `ValueError: At least one column besides the conflict column is required.` | PASS |
| TC-120 | `TestUpsertRow::test_empty_data_is_rejected` | `ValueError: data cannot be empty.` | PASS |
| TC-121 | `TestUpsertRow::test_empty_conflict_column_is_rejected` | `ValueError: conflict_column is required.` | PASS |
| TC-122 | `TestAlterTable::test_add_column` | `status="success"` and `notes` appears in `describe_table` | PASS |
| TC-123 | `TestAlterTable::test_rename_column` | `notes` renamed to `remarks` | PASS |
| TC-124 | `TestAlterTable::test_drop_column` | `notes` removed | PASS |
| TC-125 | `TestAlterTable::test_add_column_requires_column_type` | `ValueError: column_type is required when adding a column.` | PASS |
| TC-126 | `TestAlterTable::test_rename_requires_new_column` | `ValueError: new_column is required when renaming a column.` | PASS |
| TC-127 | `TestAlterTable::test_unsupported_operation_is_rejected` | `ValueError: Unsupported operation. Use add_column, rename_column, or drop_column.` | PASS |
| TC-128 | `TestAlterTable::test_empty_table_name_is_rejected` | `ValueError: Table name cannot be empty.` | PASS |
| TC-129 | `TestAlterTable::test_empty_column_name_is_rejected` | `ValueError: Column name cannot be empty.` | PASS |
| TC-130 | `TestDeleteTable::test_deleted_table_disappears` | `status="deleted"`, table gone from `list_tables` and `describe_table` | PASS |
| TC-131 | `TestDeleteTable::test_delete_is_idempotent` | Second delete also reports `status="deleted"` (`DROP TABLE IF EXISTS`) | PASS |
| TC-132 | `TestDeleteTable::test_empty_table_name_is_rejected` | `ValueError: Table name cannot be empty.` | PASS |

---

## 9. Test cases — `tests/test_anonymization_tools.py` (14)

| # | Test case | What it verifies | Result |
| --- | --- | --- | --- |
| TC-133 | `TestAnonymizeAndInsert::test_stored_row_contains_masked_values_only` | `anonymized_data` = `{'customer_id': 1, 'name': 'Neha', 'email': 'n***@example.com', 'phone': '******3210', 'city': 'Chennai'}`; the database row contains only the masked values | PASS |
| TC-134 | `TestAnonymizeAndInsert::test_non_sensitive_columns_are_kept_verbatim` | `name`, `city`, `customer_id` stored unchanged | PASS |
| TC-135 | `TestAnonymizeAndInsert::test_empty_data_is_rejected` | `ValueError: data cannot be empty` | PASS |
| TC-136 | `TestAnonymizeAndInsertRows::test_every_row_is_masked_before_insert` | `inserted: 2`, stored emails are `*@example.com` (raw `x@…`/`y@…` absent) | PASS |
| TC-137 | `TestAnonymizeAndInsertRows::test_empty_row_list_is_rejected` | `ValueError: rows cannot be empty` | PASS |
| TC-138 | `TestAnonymizeAndInsertRows::test_rows_with_different_columns_are_rejected` | `ValueError: All rows must contain the same columns.` + nothing inserted | PASS |
| TC-139 | `TestAnonymizedUpdate::test_update_values_are_masked` | `anonymized_updates == {'email': 'n**@example.com'}` and that value is stored | PASS |
| TC-140 | `TestAnonymizedUpdate::test_where_values_are_used_verbatim` | A raw PII value in `where` still matches a raw row (WHERE is not anonymized) | PASS |
| TC-141 | `TestAnonymizedUpdate::test_empty_updates_are_rejected` | `ValueError: updates cannot be empty.` | PASS |
| TC-142 | `TestAnonymizedUpdate::test_missing_where_is_rejected` | `ValueError: ...Refusing to update the entire table.` + row count unchanged | PASS |
| TC-143 | `TestAnonymizedDelete::test_matching_rows_are_deleted` | `{'status': 'success', 'table': 'customers', 'deleted_rows': 1}` | PASS |
| TC-144 | `TestAnonymizedDelete::test_missing_where_is_rejected` | `ValueError: ...Refusing to delete the entire table.` | PASS |
| TC-145 | `TestUpsertAnonymizeFlag::test_anonymize_flag_masks_stored_pii` | `anonymize=True` stores `r**@example.com` instead of `raw@example.com` | PASS |
| TC-146 | `TestUpsertAnonymizeFlag::test_pii_is_stored_verbatim_without_the_flag` | Default `anonymize=False` stores `raw@example.com` | PASS |

---

## 10. Observations from the run

Facts observed while the tests were executed; they are not guesses.

1. **README / code mismatch — phone with `+91` and no separator.** README §5.2
   lists `+919876543210` as a detected example, but the regex
   `\b(?:\+91[-\s]?)?[6-9]\d{9}\b` never matches it (`TC-005`). `+91 9876543210`
   and `+91-9876543210` are matched, and only the 10 digits are masked, so the
   output keeps the prefix: `+91 ******3210` (`TC-024`).
2. **README / code mismatch — PAN example.** README §5.3 shows
   `ABCDE1234F` → `*****1234F`, while §9 shows `*****234F`. The implementation
   returns `"*****" + value[-4:]`, i.e. `*****234F` (`TC-014`).
3. **`create_database`/`create_table` name validation is character-based only.**
   Names must match `[A-Za-z0-9_]`, everything else is rejected before any
   connection is opened (`TC-058`, `TC-096`–`TC-098`).
4. **`DuplicateTable` has no dedicated mapping**, so a duplicate
   `create_table` surfaces as the generic
   `RuntimeError: create_table: PostgreSQL operation failed.` instead of a
   specific message (`TC-100`, `TC-044`).
5. **`query()` is guarded by the statement prefix only** — anything not
   starting with `select` (after `strip()` + lowercase) is rejected before
   connecting; malformed SQL that does start with `SELECT` reaches PostgreSQL
   and is reported as `RuntimeError: query: PostgreSQL operation failed.`
   (`TC-082`–`TC-087`).
6. **`MCPServer.call_tool()` wraps tool exceptions** in
   `mcp.server.mcpserver.exceptions.UnexpectedToolError`; the original message
   is preserved on `__cause__`, and the traceback text is written to the
   server log (`TC-052`).
7. **`upsert_row` returns every column** (`RETURNING *`), so columns that were
   not supplied come back as `None` (`TC-117`).
8. **Anonymization is column-name driven.** Only the six columns in
   `SENSITIVE_COLUMNS` are masked; a PII value in any other column (e.g.
   `notes`) is stored untouched (`TC-030`), and `upsert_row` only masks when
   `anonymize=True` (`TC-145`, `TC-146`).
9. **IP octets are not range-checked**: `999.999.999.999` is masked as an IP
   (`TC-027`).
10. **Test isolation is clean.** Every integration test uses a temporary
    database `pytest_tmp_<hex>` that is dropped in fixture teardown; after the
    recorded run `list_databases()` returned only the pre-existing databases
    (`asset_management`, `data`, `ev_charge`, `pandas_project`, `postgres`).

## 11. Files added / changed

| Path | Change |
| --- | --- |
| `tests/conftest.py` | fixtures, `src/` import path, `requires_postgres` marker |
| `tests/test_pii_anonymizer.py` | 32 unit tests |
| `tests/test_exception_mapping.py` | 14 unit tests |
| `tests/test_mcp_registration.py` | 6 MCP-layer tests |
| `tests/test_database_discovery.py` | 13 integration tests |
| `tests/test_schema_and_read.py` | 27 integration tests |
| `tests/test_write_operations.py` | 40 integration tests |
| `tests/test_anonymization_tools.py` | 14 integration tests |
| `pyproject.toml` | added `pytest` dev dependency and `[tool.pytest.ini_options] testpaths = ["tests"]` |
