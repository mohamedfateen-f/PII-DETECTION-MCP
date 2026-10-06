import logging

import psycopg

from mcp.server import MCPServer
from psycopg import sql
from pii_anonymizer import anonymize_data

from database import get_connection


mcp = MCPServer("PostgreSQL MCP")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


def _handle_exception(tool_name: str, exc: Exception) -> None:
    """Convert database and application exceptions into useful MCP errors.

    The original exception is preserved as the cause so debugging information
    is not lost, while the raised error gives the MCP caller a clear message.
    """

    logger.exception("MCP tool '%s' failed", tool_name)

    if isinstance(exc, ValueError):
        raise ValueError(str(exc)) from exc

    if isinstance(exc, psycopg.errors.UniqueViolation):
        raise ValueError(
            f"{tool_name}: a unique constraint was violated."
        ) from exc

    if isinstance(exc, psycopg.errors.ForeignKeyViolation):
        raise ValueError(
            f"{tool_name}: a foreign-key constraint was violated."
        ) from exc

    if isinstance(exc, psycopg.errors.NotNullViolation):
        raise ValueError(
            f"{tool_name}: a required column value is missing."
        ) from exc

    if isinstance(exc, psycopg.errors.CheckViolation):
        raise ValueError(
            f"{tool_name}: a database check constraint was violated."
        ) from exc

    if isinstance(exc, psycopg.errors.UndefinedTable):
        raise ValueError(
            f"{tool_name}: the requested table does not exist."
        ) from exc

    if isinstance(exc, psycopg.errors.UndefinedColumn):
        raise ValueError(
            f"{tool_name}: the requested column does not exist."
        ) from exc

    if isinstance(exc, psycopg.errors.InvalidCatalogName):
        raise ValueError(
            f"{tool_name}: the requested database does not exist."
        ) from exc

    if isinstance(exc, psycopg.errors.InsufficientPrivilege):
        raise PermissionError(
            f"{tool_name}: PostgreSQL permission denied."
        ) from exc

    if isinstance(exc, psycopg.OperationalError):
        raise ConnectionError(
            f"{tool_name}: could not connect to PostgreSQL."
        ) from exc

    if isinstance(exc, psycopg.Error):
        raise RuntimeError(
            f"{tool_name}: PostgreSQL operation failed."
        ) from exc

    raise RuntimeError(
        f"{tool_name}: an unexpected error occurred."
    ) from exc


# DATABASE DISCOVERY
@mcp.tool()
def list_databases() -> list[str]:
    """List all PostgreSQL databases available to the current user."""

    try:

        with get_connection("postgres") as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT datname
                    FROM pg_database
                    WHERE datallowconn = true
                    AND datistemplate = false
                    ORDER BY datname;
                    """
                )

                return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        _handle_exception("list_databases", exc)

@mcp.tool()
def create_database(database: str) -> dict:
    """
    Create a new PostgreSQL database.

    The MCP server connects to the default 'postgres'
    database and creates the requested database.
    """

    try:

        if not database:
            raise ValueError("Database name cannot be empty.")

        # Basic validation for database name
        if not database.replace("_", "").isalnum():
            raise ValueError(
                "Database name can contain only letters, "
                "numbers, and underscores."
            )

        with get_connection("postgres") as conn:

            # CREATE DATABASE must run outside a transaction
            conn.autocommit = True

            with conn.cursor() as cur:

                # Check whether database already exists
                cur.execute(
                    """
                    SELECT 1
                    FROM pg_database
                    WHERE datname = %s;
                    """,
                    (database,)
                )

                if cur.fetchone():
                    return {
                        "status": "already_exists",
                        "database": database,
                        "message": f"Database '{database}' already exists."
                    }

                # Database name is validated above.
                query = sql.SQL(
                    "CREATE DATABASE {}"
                ).format(
                    sql.Identifier(database)
                )

                cur.execute(query)

        return {
            "status": "created",
            "database": database,
            "message": f"Database '{database}' created successfully."
        }
    except Exception as exc:
        _handle_exception("create_database", exc)


@mcp.tool()
def delete_database(database: str) -> dict:
    """
    Delete a PostgreSQL database.

    The server connects to the default 'postgres' database.
    The target database cannot be the current connection database.
    """

    try:

        if not database:
            raise ValueError("Database name cannot be empty.")

        if not database.replace("_", "").isalnum():
            raise ValueError(
                "Database name can contain only letters, "
                "numbers, and underscores."
            )

        if database == "postgres":
            raise ValueError("Deleting the postgres database is not allowed.")

        with get_connection("postgres") as conn:
            conn.autocommit = True

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM pg_database
                    WHERE datname = %s;
                    """,
                    (database,),
                )

                if not cur.fetchone():
                    return {
                        "status": "not_found",
                        "database": database,
                        "message": f"Database '{database}' does not exist.",
                    }

                query = sql.SQL(
                    "DROP DATABASE {}"
                ).format(
                    sql.Identifier(database)
                )

                cur.execute(query)

        return {
            "status": "deleted",
            "database": database,
            "message": f"Database '{database}' deleted successfully.",
        }
    except Exception as exc:
        _handle_exception("delete_database", exc)

@mcp.tool()
def database_info(database: str) -> dict:
    """Return basic information about a PostgreSQL database."""

    try:

        with get_connection(database) as conn:
            with conn.cursor() as cur:

                cur.execute("SELECT current_database();")
                db_name = cur.fetchone()[0]

                cur.execute("SELECT current_user;")
                user = cur.fetchone()[0]

                cur.execute("SELECT version();")
                version = cur.fetchone()[0]

                return {
                    "database": db_name,
                    "user": user,
                    "version": version,
                }
    except Exception as exc:
        _handle_exception("database_info", exc)


# SCHEMA DISCOVERY

@mcp.tool()
def list_schemas(database: str) -> list[str]:
    """List schemas in a PostgreSQL database."""

    try:

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT schema_name
                    FROM information_schema.schemata
                    WHERE schema_name NOT IN (
                        'pg_catalog',
                        'information_schema'
                    )
                    ORDER BY schema_name;
                    """
                )

                return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        _handle_exception("list_schemas", exc)


@mcp.tool()
def list_tables(
    database: str,
    schema: str = "public",
) -> list[str]:
    """List tables in a PostgreSQL database schema."""

    try:

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name;
                    """,
                    (schema,),
                )

                return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        _handle_exception("list_tables", exc)


@mcp.tool()
def describe_table(
    database: str,
    table: str,
    schema: str = "public",
) -> list[dict]:
    """Return column information for a PostgreSQL table."""

    try:

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        column_name,
                        data_type,
                        is_nullable,
                        column_default
                    FROM information_schema.columns
                    WHERE table_schema = %s
                    AND table_name = %s
                    ORDER BY ordinal_position;
                    """,
                    (schema, table),
                )

                rows = cur.fetchall()

                return [
                    {
                        "column_name": row[0],
                        "data_type": row[1],
                        "nullable": row[2],
                        "default": row[3],
                    }
                    for row in rows
                ]
    except Exception as exc:
        _handle_exception("describe_table", exc)


# READ OPERATIONS

@mcp.tool()
def read_table(
    database: str,
    table: str,
    schema: str = "public",
    limit: int = 100,
) -> list[dict]:
    """
    Read rows from a PostgreSQL table.

    Only SELECT/read operations are performed.
    """

    try:

        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")

        query = sql.SQL(
            """
            SELECT *
            FROM {}.{}
            LIMIT %s
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
        )

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (limit,))

                columns = [column.name for column in cur.description]

                return [
                    dict(zip(columns, row))
                    for row in cur.fetchall()
                ]
    except Exception as exc:
        _handle_exception("read_table", exc)


@mcp.tool()
def query(
    database: str,
    sql_query: str,
) -> list[dict]:
    """
    Execute a read-only SQL SELECT query.

    Only SELECT statements are allowed.
    """

    try:

        cleaned_sql = sql_query.strip().lower()

        if not cleaned_sql.startswith("select"):
            raise ValueError(
                "Only SELECT queries are allowed."
            )

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(sql_query)

                columns = [
                    column.name
                    for column in cur.description
                ]

                return [
                    dict(zip(columns, row))
                    for row in cur.fetchall()
                ]
    except Exception as exc:
        _handle_exception("query", exc)


@mcp.tool()
def count_rows(
    database: str,
    table: str,
    schema: str = "public",
) -> int:
    """Return the number of rows in a table."""

    try:

        query = sql.SQL(
            """
            SELECT COUNT(*)
            FROM {}.{}
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
        )

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(query)

                return cur.fetchone()[0]
    except Exception as exc:
        _handle_exception("count_rows", exc)


# INSERT

@mcp.tool()
def insert_row(
    database: str,
    table: str,
    data: dict,
    schema: str = "public",
) -> dict:
    """
    Insert or add one row into a PostgreSQL table.

    Example:
    {
        "station_id": "EVCS-1001",
        "city": "Chennai",
        "charger_type": "DC Fast CCS2"
    }
    """

    try:

        if not data:
            raise ValueError("data cannot be empty")

        columns = list(data.keys())
        values = list(data.values())

        query = sql.SQL(
            """
            INSERT INTO {}.{} ({})
            VALUES ({})
            RETURNING *
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(", ").join(
                sql.Identifier(column)
                for column in columns
            ),
            sql.SQL(", ").join(
                sql.Placeholder()
                for _ in values
            ),
        )

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)

                columns = [
                    column.name
                    for column in cur.description
                ]

                row = cur.fetchone()

                return dict(zip(columns, row))
    except Exception as exc:
        _handle_exception("insert_row", exc)


@mcp.tool()
def insert_rows(
    database: str,
    table: str,
    rows: list[dict],
    schema: str = "public",
) -> dict:
    """
    Insert or add multiple rows into a PostgreSQL table.

    All rows must contain the same columns.
    """

    try:

        if not rows:
            raise ValueError("rows cannot be empty")

        columns = list(rows[0].keys())

        for row in rows:
            if set(row.keys()) != set(columns):
                raise ValueError(
                    "All rows must contain the same columns."
                )

        query = sql.SQL(
            """
            INSERT INTO {}.{} ({})
            VALUES ({})
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(", ").join(
                sql.Identifier(column)
                for column in columns
            ),
            sql.SQL(", ").join(
                sql.Placeholder()
                for _ in columns
            ),
        )

        values = [
            tuple(row[column] for column in columns)
            for row in rows
        ]

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.executemany(query, values)

                return {
                    "inserted": len(rows),
                    "table": table,
                }
    except Exception as exc:
        _handle_exception("insert_rows", exc)


# UPDATE

@mcp.tool()
def update_rows(
    database: str,
    table: str,
    updates: dict,
    where: dict,
    schema: str = "public",
) -> dict:
    """
    Update rows in a PostgreSQL table.

    Example:

    updates:
    {
        "city": "Chennai"
    }

    where:
    {
        "station_id": "EVCS-1001"
    }
    """

    try:

        if not updates:
            raise ValueError("updates cannot be empty")

        if not where:
            raise ValueError(
                "WHERE conditions are required. "
                "Refusing to update the entire table."
            )

        set_parts = [
            sql.SQL("{} = {}").format(
                sql.Identifier(column),
                sql.Placeholder(),
            )
            for column in updates
        ]

        where_parts = [
            sql.SQL("{} = {}").format(
                sql.Identifier(column),
                sql.Placeholder(),
            )
            for column in where
        ]

        query = sql.SQL(
            """
            UPDATE {}.{}
            SET {}
            WHERE {}
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(", ").join(set_parts),
            sql.SQL(" AND ").join(where_parts),
        )

        values = list(updates.values()) + list(where.values())

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)

                return {
                    "updated_rows": cur.rowcount,
                    "table": table,
                }
    except Exception as exc:
        _handle_exception("update_rows", exc)


# DELETE

@mcp.tool()
def delete_rows(
    database: str,
    table: str,
    where: dict,
    schema: str = "public",
) -> dict:
    """
    Delete rows from a PostgreSQL table.

    WHERE conditions are mandatory to prevent accidental
    deletion of an entire table.
    """

    try:

        if not where:
            raise ValueError(
                "WHERE conditions are required. "
                "Refusing to delete the entire table."
            )

        where_parts = [
            sql.SQL("{} = {}").format(
                sql.Identifier(column),
                sql.Placeholder(),
            )
            for column in where
        ]

        query = sql.SQL(
            """
            DELETE FROM {}.{}
            WHERE {}
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(" AND ").join(where_parts),
        )

        values = list(where.values())

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(query, values)

                return {
                    "deleted_rows": cur.rowcount,
                    "table": table,
                }
    except Exception as exc:
        _handle_exception("delete_rows", exc)


# TABLE STATISTICS

@mcp.tool()
def table_stats(
    database: str,
    table: str,
    schema: str = "public",
) -> dict:
    """Return basic statistics about a PostgreSQL table."""

    try:

        query = sql.SQL(
            """
            SELECT
                COUNT(*) AS row_count
            FROM {}.{}
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
        )

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(query)

                row_count = cur.fetchone()[0]

                return {
                    "database": database,
                    "schema": schema,
                    "table": table,
                    "row_count": row_count,
                }
    except Exception as exc:
        _handle_exception("table_stats", exc)



@mcp.tool()
def anonymize_and_insert(
    database: str,
    table: str,
    data: dict,
    schema: str = "public",
) -> dict:
    """
    Anonymize PII in the supplied data and insert
    only the anonymized data into PostgreSQL.

    The original PII is never inserted into the database.
    """

    try:

        if not data:
            raise ValueError("data cannot be empty")

        # 1. Anonymize incoming data

        anonymized_data = anonymize_data(data)

        columns = list(anonymized_data.keys())
        values = list(anonymized_data.values())

        # 2. Build INSERT query

        query = sql.SQL(
            """
            INSERT INTO {}.{} ({})
            VALUES ({})
            RETURNING *
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),

            sql.SQL(", ").join(
                sql.Identifier(column)
                for column in columns
            ),

            sql.SQL(", ").join(
                sql.Placeholder()
                for _ in values
            ),
        )

        # 3. Insert anonymized data

        with get_connection(database) as conn:

            with conn.cursor() as cur:

                cur.execute(
                    query,
                    values
                )

                result_columns = [
                    column.name
                    for column in cur.description
                ]

                row = cur.fetchone()

        inserted_row = dict(
            zip(result_columns, row)
        )

        return {
            "status": "success",
            "message": "Data anonymized and inserted successfully.",
            "anonymized_data": anonymized_data,
            "inserted_row": inserted_row,
        }
    except Exception as exc:
        _handle_exception("anonymize_and_insert", exc)


@mcp.tool()
def anonymized_update(
    database: str,
    table: str,
    updates: dict,
    where: dict,
    schema: str = "public",
) -> dict:
    """
    Anonymize PII in update data and update PostgreSQL rows.

    WHERE conditions are mandatory.
    """

    try:

        if not updates:
            raise ValueError("updates cannot be empty.")

        if not where:
            raise ValueError(
                "WHERE conditions are required. "
                "Refusing to update the entire table."
            )

        # Anonymize only the values being updated
        anonymized_updates = anonymize_data(updates)

        set_parts = [
            sql.SQL("{} = {}").format(
                sql.Identifier(column),
                sql.Placeholder(),
            )
            for column in anonymized_updates
        ]

        where_parts = [
            sql.SQL("{} = {}").format(
                sql.Identifier(column),
                sql.Placeholder(),
            )
            for column in where
        ]

        query = sql.SQL(
            """
            UPDATE {}.{}
            SET {}
            WHERE {}
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(", ").join(set_parts),
            sql.SQL(" AND ").join(where_parts),
        )

        values = (
            list(anonymized_updates.values())
            + list(where.values())
        )

        with get_connection(database) as conn:
            with conn.cursor() as cur:

                cur.execute(query, values)

                updated_rows = cur.rowcount

        return {
            "status": "success",
            "table": table,
            "updated_rows": updated_rows,
            "anonymized_updates": anonymized_updates,
        }
    except Exception as exc:
        _handle_exception("anonymized_update", exc)



@mcp.tool()
def anonymize_and_insert_rows(
    database: str,
    table: str,
    rows: list[dict],
    schema: str = "public",
) -> dict:
    """
    Anonymize PII in multiple records and insert
    only anonymized records into PostgreSQL.
    """

    try:

        if not rows:
            raise ValueError("rows cannot be empty")

        # Anonymize every row

        anonymized_rows = [
            anonymize_data(row)
            for row in rows
        ]


        columns = list(anonymized_rows[0].keys())

        for row in anonymized_rows:

            if set(row.keys()) != set(columns):

                raise ValueError(
                    "All rows must contain the same columns."
                )

        # Build query

        query = sql.SQL(
            """
            INSERT INTO {}.{} ({})
            VALUES ({})
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),

            sql.SQL(", ").join(
                sql.Identifier(column)
                for column in columns
            ),

            sql.SQL(", ").join(
                sql.Placeholder()
                for _ in columns
            ),
        )

        # Prepare values

        values = [
            tuple(
                row[column]
                for column in columns
            )
            for row in anonymized_rows
        ]

        # Insert

        with get_connection(database) as conn:

            with conn.cursor() as cur:

                cur.executemany(
                    query,
                    values
                )

        return {
            "status": "success",
            "inserted": len(anonymized_rows),
            "table": table,
            "message": (
                "All records were anonymized "
                "before database insertion."
            ),
        }
    except Exception as exc:
        _handle_exception("anonymize_and_insert_rows", exc)


@mcp.tool()
def anonymized_delete(
    database: str,
    table: str,
    where: dict,
    schema: str = "public",
) -> dict:
    """
    Delete rows from PostgreSQL.

    WHERE conditions are mandatory.
    """

    try:

        if not where:
            raise ValueError(
                "WHERE conditions are required. "
                "Refusing to delete the entire table."
            )

        where_parts = [
            sql.SQL("{} = {}").format(
                sql.Identifier(column),
                sql.Placeholder(),
            )
            for column in where
        ]

        query = sql.SQL(
            """
            DELETE FROM {}.{}
            WHERE {}
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(" AND ").join(where_parts),
        )

        values = list(where.values())

        with get_connection(database) as conn:
            with conn.cursor() as cur:

                cur.execute(query, values)

                deleted_rows = cur.rowcount

        return {
            "status": "success",
            "table": table,
            "deleted_rows": deleted_rows,
        }
    except Exception as exc:
        _handle_exception("anonymized_delete", exc)

@mcp.tool()
def create_table(
    database: str,
    table: str,
    columns: dict[str, str],
    schema: str = "public",
) -> dict:
    """
    Create a PostgreSQL table.

    Example:

    columns = {
        "customer_id": "SERIAL PRIMARY KEY",
        "name": "VARCHAR(100)",
        "email": "VARCHAR(255)",
        "phone": "VARCHAR(20)",
        "pan": "VARCHAR(20)",
        "aadhaar": "VARCHAR(20)",
        "city": "VARCHAR(100)"
    }
    """

    try:

        if not table:
            raise ValueError("Table name cannot be empty.")

        if not columns:
            raise ValueError("columns cannot be empty.")

        # Basic table-name validation
        if not table.replace("_", "").isalnum():
            raise ValueError(
                "Table name can contain only letters, "
                "numbers, and underscores."
            )

        # Build column definitions
        column_definitions = []

        for column_name, column_type in columns.items():

            if not column_name.replace("_", "").isalnum():
                raise ValueError(
                    f"Invalid column name: {column_name}"
                )

            column_definitions.append(
                sql.SQL("{} {}").format(
                    sql.Identifier(column_name),
                    sql.SQL(column_type)
                )
            )

        query = sql.SQL(
            "CREATE TABLE {}.{} ({})"
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            sql.SQL(", ").join(column_definitions)
        )

        with get_connection(database) as conn:

            with conn.cursor() as cur:

                cur.execute(query)

        return {
            "status": "created",
            "database": database,
            "schema": schema,
            "table": table,
            "columns": columns,
            "message": (
                f"Table '{schema}.{table}' "
                "created successfully."
            ),
        }
    except Exception as exc:
        _handle_exception("create_table", exc)


@mcp.tool()
def delete_table(
    database: str,
    table: str,
    schema: str = "public",
) -> dict:
    """
    Delete a PostgreSQL table.
    """

    try:

        if not table:
            raise ValueError("Table name cannot be empty.")

        with get_connection(database) as conn:
            with conn.cursor() as cur:

                query = sql.SQL(
                    "DROP TABLE IF EXISTS {}.{}"
                ).format(
                    sql.Identifier(schema),
                    sql.Identifier(table),
                )

                cur.execute(query)

        return {
            "status": "deleted",
            "database": database,
            "schema": schema,
            "table": table,
            "message": f"Table '{schema}.{table}' deleted successfully.",
        }
    except Exception as exc:
        _handle_exception("delete_table", exc)


@mcp.tool()
def alter_table(
    database: str,
    table: str,
    operation: str,
    column: str,
    new_column: str | None = None,
    column_type: str | None = None,
    schema: str = "public",
) -> dict:
    """
    Alter a PostgreSQL table.

    Supported operations:
    - add_column
    - rename_column
    - drop_column
    """

    try:

        if not table:
            raise ValueError("Table name cannot be empty.")

        if not column:
            raise ValueError("Column name cannot be empty.")

        if operation == "add_column":

            if not column_type:
                raise ValueError(
                    "column_type is required when adding a column."
                )

            query = sql.SQL(
                "ALTER TABLE {}.{} ADD COLUMN {} {}"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Identifier(column),
                sql.SQL(column_type),
            )

        elif operation == "rename_column":

            if not new_column:
                raise ValueError(
                    "new_column is required when renaming a column."
                )

            query = sql.SQL(
                "ALTER TABLE {}.{} RENAME COLUMN {} TO {}"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Identifier(column),
                sql.Identifier(new_column),
            )

        elif operation == "drop_column":

            query = sql.SQL(
                "ALTER TABLE {}.{} DROP COLUMN {}"
            ).format(
                sql.Identifier(schema),
                sql.Identifier(table),
                sql.Identifier(column),
            )

        else:
            raise ValueError(
                "Unsupported operation. "
                "Use add_column, rename_column, or drop_column."
            )

        with get_connection(database) as conn:
            with conn.cursor() as cur:
                cur.execute(query)

        return {
            "status": "success",
            "database": database,
            "schema": schema,
            "table": table,
            "operation": operation,
            "column": column,
            "message": "Table altered successfully.",
        }
    except Exception as exc:
        _handle_exception("alter_table", exc)



@mcp.tool()
def upsert_row(
    database: str,
    table: str,
    data: dict,
    conflict_column: str,
    schema: str = "public",
    anonymize: bool = False,
) -> dict:
    """
    Insert a row or update it when conflict_column already exists.

    Example:

    data = {
        "customer_id": 1,
        "name": "John",
        "email": "john@example.com"
    }

    conflict_column = "customer_id"
    """

    try:

        if not data:
            raise ValueError("data cannot be empty.")

        if not conflict_column:
            raise ValueError("conflict_column is required.")

        if anonymize:
            data = anonymize_data(data)

        columns = list(data.keys())
        values = list(data.values())

        update_columns = [
            column
            for column in columns
            if column != conflict_column
        ]

        if not update_columns:
            raise ValueError(
                "At least one column besides the conflict column "
                "is required."
            )

        insert_columns = sql.SQL(", ").join(
            sql.Identifier(column)
            for column in columns
        )

        placeholders = sql.SQL(", ").join(
            sql.Placeholder()
            for _ in values
        )

        update_parts = sql.SQL(", ").join(
            sql.SQL("{} = EXCLUDED.{}").format(
                sql.Identifier(column),
                sql.Identifier(column),
            )
            for column in update_columns
        )

        query = sql.SQL(
            """
            INSERT INTO {}.{} ({})
            VALUES ({})
            ON CONFLICT ({})
            DO UPDATE SET {}
            RETURNING *
            """
        ).format(
            sql.Identifier(schema),
            sql.Identifier(table),
            insert_columns,
            placeholders,
            sql.Identifier(conflict_column),
            update_parts,
        )

        with get_connection(database) as conn:
            with conn.cursor() as cur:

                cur.execute(query, values)

                result_columns = [
                    column.name
                    for column in cur.description
                ]

                row = cur.fetchone()

        return {
            "status": "success",
            "operation": "upsert",
            "row": dict(zip(result_columns, row)),
        }
    except Exception as exc:
        _handle_exception("upsert_row", exc)

# SERVER START
if __name__ == "__main__":
    mcp.run()