from __future__ import annotations


import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


import anyio


from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.elicitation import AcceptedElicitation, elicit_with_validation
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "insert_row",
        "insert_rows",
        "update_rows",
        "delete_rows",
        "upsert_row",
        "anonymize_and_insert",
        "anonymize_and_insert_rows",
        "anonymized_update",
        "anonymized_delete",
        "create_table",
        "delete_table",
        "alter_table",
        "create_database",
        "delete_database",
    }
)


DESTRUCTIVE_TOOLS: frozenset[str] = frozenset(
    {
        "delete_rows",
        "anonymized_delete",
        "delete_table",
        "delete_database",
        "alter_table",
    }
)


ANONYMIZING_TOOLS: frozenset[str] = frozenset(
    {
        "anonymize_and_insert",
        "anonymize_and_insert_rows",
        "anonymized_update",
        "anonymized_delete",
    }
)


ENV_CONFIRM = "PG_MCP_CONFIRM_DML"
ENV_ALLOWLIST = "PG_MCP_DML_ALLOWLIST"
ENV_ALLOW_NO_ELICITATION = "PG_MCP_DML_ALLOW_NO_ELICITATION"
ENV_TIMEOUT = "PG_MCP_CONFIRM_TIMEOUT"


DEFAULT_TIMEOUT_SECONDS = 60.0


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


_MAX_VALUE_CHARS = 120
_MAX_PAIRS = 10


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean environment variable, tolerating typos."""

    raw = os.getenv(name)

    if raw is None:
        return default

    normalized = raw.strip().lower()

    if normalized in _TRUE_VALUES:
        return True

    if normalized in _FALSE_VALUES:
        return False

    logger.warning(
        "Ignoring unrecognised value %r for %s; using %s.",
        raw,
        name,
        default,
    )

    return default


def _env_timeout(name: str, default: float) -> float:
    """Read a positive number of seconds, tolerating junk values."""

    raw = os.getenv(name)

    if raw is None or raw.strip() == "":
        return default

    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring unparsable value %r for %s; using %s seconds.",
            raw,
            name,
            default,
        )
        return default

    if seconds <= 0:
        logger.warning(
            "%s must be greater than 0 (got %r); using %s seconds.",
            name,
            raw,
            default,
        )
        return default

    return seconds


@dataclass(frozen=True)
class ConfirmationSettings:
    """Resolved confirmation policy."""

    enabled: bool = True
    allowlist: frozenset[str] = frozenset()
    allow_without_elicitation: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> ConfirmationSettings:
        raw_allowlist = os.getenv(ENV_ALLOWLIST, "")

        allowlist = frozenset(
            name.strip()
            for name in raw_allowlist.split(",")
            if name.strip()
        )

        unknown = allowlist - MUTATING_TOOLS

        if unknown:
            logger.warning(
                "%s names tools that are not guarded: %s",
                ENV_ALLOWLIST,
                ", ".join(sorted(unknown)),
            )

        return cls(
            enabled=_env_flag(ENV_CONFIRM, True),
            allowlist=allowlist,
            allow_without_elicitation=_env_flag(ENV_ALLOW_NO_ELICITATION, False),
            timeout_seconds=_env_timeout(ENV_TIMEOUT, DEFAULT_TIMEOUT_SECONDS),
        )

    def needs_confirmation(self, tool_name: str) -> bool:
        if not self.enabled:
            return False

        if tool_name in self.allowlist:
            return False

        return tool_name in MUTATING_TOOLS


class ConfirmationResponse(BaseModel):
    """The form the client is expected to render for the operator.

    Deliberately primitive-only: the MCP elicitation schema admits nothing but
    strings, numbers, booleans and enums.
    """

    approved: bool = Field(
        default=False,
        title="Approved",
        description=(
            "Set to true to execute the operation as shown, false to cancel it."
        ),
    )


def _short(value: Any, limit: int = _MAX_VALUE_CHARS) -> str:
    """Render a value on a single line, truncated."""

    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except (TypeError, ValueError):
            text = str(value)

    text = " ".join(text.split())

    if len(text) > limit:
        text = text[: limit - 1] + "…"

    return text


def _pairs(mapping: Any) -> list[str]:
    """Render a ``{column: value}`` mapping as indented ``column = value`` lines."""

    if not isinstance(mapping, dict):
        return ["    " + _short(mapping)]

    if not mapping:
        return ["    (empty)"]

    items = list(mapping.items())
    lines = [f"    {column} = {_short(value, 80)}" for column, value in items[:_MAX_PAIRS]]

    if len(items) > _MAX_PAIRS:
        lines.append(f"    … and {len(items) - _MAX_PAIRS} more")

    return lines


def _target(args: dict[str, Any]) -> str:
    schema = args.get("schema") or "public"
    table = args.get("table")

    return f"{schema}.{table}" if table else "(unspecified)"


def _database(args: dict[str, Any]) -> list[str]:
    return [f"Database: {args.get('database') or '(unspecified)'}"]


def _render_create_database(args: dict[str, Any]) -> list[str]:
    return [f"Create a new database named {args.get('database')!r}."]


def _render_delete_database(args: dict[str, Any]) -> list[str]:
    database = args.get("database")

    return [
        (
            f"DROP DATABASE {database!r}. The database and everything in it "
            "is removed."
        )
    ]


def _render_insert_one(args: dict[str, Any], masked: bool) -> list[str]:
    data = args.get("data")

    return [
        *_database(args),
        f"Target: {_target(args)}",
        f"Rows: 1{' (PII will be masked)' if masked else ''}",
        "Values:",
        *_pairs(data),
    ]


def _render_insert_many(args: dict[str, Any], masked: bool) -> list[str]:
    rows = args.get("rows")

    if not isinstance(rows, list):
        rows = []

    columns = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else []

    lines = [
        *_database(args),
        f"Target: {_target(args)}",
        f"Rows: {len(rows)}{' (PII will be masked)' if masked else ''}",
        f"Columns: {_short(columns) if columns else '(none)'}",
    ]

    for index, row in enumerate(rows[:_MAX_PAIRS]):
        rendered = ", ".join(f"{k}={_short(v, 40)}" for k, v in row.items())
        lines.append(f"    [{index}] {rendered}")

    if len(rows) > _MAX_PAIRS:
        lines.append(f"    … and {len(rows) - _MAX_PAIRS} more rows")

    return lines


def _render_update(args: dict[str, Any], masked: bool) -> list[str]:
    return [
        *_database(args),
        f"Target: {_target(args)}",
        *(
            ["New values have their PII masked before the write."]
            if masked
            else []
        ),
        "SET:",
        *_pairs(args.get("updates")),
        "WHERE:",
        *_pairs(args.get("where")),
    ]


def _render_delete(args: dict[str, Any]) -> list[str]:
    return [
        *_database(args),
        f"Target: {_target(args)}",
        "Matching rows are permanently deleted.",
        "WHERE:",
        *_pairs(args.get("where")),
    ]


def _render_create_table(args: dict[str, Any]) -> list[str]:
    columns = args.get("columns")

    return [
        *_database(args),
        f"Target: {_target(args)}",
        "Fails if the table already exists.",
        "Columns:",
        *_pairs(columns),
    ]


def _render_delete_table(args: dict[str, Any]) -> list[str]:
    return [
        *_database(args),
        f"Target: {_target(args)}",
        "DROP TABLE IF EXISTS. The table and all of its rows are removed.",
    ]


def _render_alter_table(args: dict[str, Any]) -> list[str]:
    operation = args.get("operation")
    column = args.get("column")

    detail: list[str] = []

    for key, label in (
        ("new_column", "New name"),
        ("column_type", "New type"),
    ):
        if args.get(key):
            detail.append(f"    {label}: {args[key]}")

    return [
        *_database(args),
        f"Target: {_target(args)}",
        f"Operation: {operation} on column {column!r}",
        *detail,
    ]


def _render_upsert(args: dict[str, Any]) -> list[str]:
    lines = [
        *_database(args),
        f"Target: {_target(args)}",
        f"Conflict column: {args.get('conflict_column')}",
        f"Rows: up to 1{' (PII will be masked)' if args.get('anonymize') else ''}",
        "Values:",
        *_pairs(args.get("data")),
    ]

    return lines


_PREVIEWS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "create_database": _render_create_database,
    "delete_database": _render_delete_database,
    "insert_row": lambda a: _render_insert_one(a, masked=False),
    "insert_rows": lambda a: _render_insert_many(a, masked=False),
    "anonymize_and_insert": lambda a: _render_insert_one(a, masked=True),
    "anonymize_and_insert_rows": lambda a: _render_insert_many(a, masked=True),
    "update_rows": lambda a: _render_update(a, masked=False),
    "anonymized_update": lambda a: _render_update(a, masked=True),
    "delete_rows": _render_delete,
    "anonymized_delete": _render_delete,
    "create_table": _render_create_table,
    "delete_table": _render_delete_table,
    "alter_table": _render_alter_table,
    "upsert_row": _render_upsert,
}


def build_prompt(tool_name: str, arguments: dict[str, Any]) -> str:
    """Compose the operator-facing approval prompt for a mutating tool call."""

    renderer = _PREVIEWS.get(tool_name)
    body = (
        renderer(arguments)
        if renderer is not None
        else [f"Arguments: {_short(arguments)}"]
    )

    if tool_name in DESTRUCTIVE_TOOLS:
        risk = (
            "Risk: DESTRUCTIVE - this may remove or rewrite existing data "
            "irreversibly."
        )
    elif tool_name in ANONYMIZING_TOOLS:
        risk = "Risk: writes PII-masked values to the database."
    else:
        risk = "Risk: modifies the database."

    return "\n".join(
        [
            f"PostgreSQL MCP - approval required before running '{tool_name}'.",
            "",
            *body,
            "",
            risk,
            "",
            (
                "Review the details above, then approve to run the "
                "statement or cancel to leave the database unchanged."
            ),
        ]
    )


def supports_form_elicitation(session: Any) -> bool:
    """Return whether the client can answer a form-mode elicitation.

    The SDK's own ``check_client_capability`` only tests that *some* form of
    elicitation exists, which is not enough: a 2025-11-25 client may advertise
    URL mode alone, and a form request to it would fail at the protocol level.
    """

    capabilities = getattr(session, "client_capabilities", None)
    elicitation = getattr(capabilities, "elicitation", None)

    if elicitation is None:
        return False

    if elicitation.form is not None:
        return True

    return elicitation.url is None


def _refusal(text: str) -> CallToolResult:
    """Build the tool-level error returned to the agent when a call is denied."""

    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        is_error=True,
    )


UNSUPPORTED_CLIENT_MESSAGE = (
    "{tool}: refused to run because the connected MCP client does not support "
    "elicitation, so no confirmation could be collected.\n"
    "Use a client that can display an approval prompt, or set "
    f"{ENV_ALLOW_NO_ELICITATION}=1 to allow unattended writes on a trusted "
    "connection."
)


DECLINED_MESSAGE = (
    "{tool}: the user declined this operation, so nothing was executed."
)


TIMEOUT_MESSAGE = (
    "{tool}: no confirmation was received within {seconds:g}s, so nothing was "
    "executed.\n"
    "The client accepted the approval request but never answered it, which "
    "usually means it cannot render an elicitation dialog. To let writes "
    f"through on a trusted connection, set {ENV_ALLOW_NO_ELICITATION}=1. To "
    f"change the wait, set {ENV_TIMEOUT} (seconds)."
)


class ConfirmationMiddleware:
    """Blocks mutating ``tools/call`` requests until the operator approves."""

    def __init__(self, settings: ConfirmationSettings | None = None) -> None:
        self.settings = settings or ConfirmationSettings.from_env()

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)

        params = ctx.params or {}
        tool_name = params.get("name")

        if not isinstance(tool_name, str):
            return await call_next(ctx)

        if not self.settings.needs_confirmation(tool_name):
            return await call_next(ctx)

        arguments = params.get("arguments") or {}

        if not isinstance(arguments, dict):
            arguments = {}

        logger.info(
            "Confirmation requested for tool '%s' (request %s)", tool_name, ctx.request_id
        )

        if not supports_form_elicitation(ctx.session):
            if not self.settings.allow_without_elicitation:
                logger.warning(
                    "Denying '%s': client lacks elicitation support (request %s)",
                    tool_name,
                    ctx.request_id,
                )
                return _refusal(
                    UNSUPPORTED_CLIENT_MESSAGE.format(tool=tool_name)
                )

            logger.warning(
                "Running '%s' without confirmation: client lacks elicitation "
                "support but %s is set (request %s)",
                tool_name,
                ENV_ALLOW_NO_ELICITATION,
                ctx.request_id,
            )
            return await call_next(ctx)

        timeout = self.settings.timeout_seconds

        try:
            with anyio.fail_after(timeout):
                result = await elicit_with_validation(
                    session=ctx.session,
                    message=build_prompt(tool_name, arguments),
                    schema=ConfirmationResponse,
                    related_request_id=ctx.request_id,
                )
        except TimeoutError:
            logger.warning(
                "Denying '%s': no confirmation received within %ss (request %s)",
                tool_name,
                timeout,
                ctx.request_id,
            )

            if not self.settings.allow_without_elicitation:
                return _refusal(TIMEOUT_MESSAGE.format(tool=tool_name, seconds=timeout))

            logger.warning(
                "Running '%s' after an unanswered prompt: %s is set (request %s)",
                tool_name,
                ENV_ALLOW_NO_ELICITATION,
                ctx.request_id,
            )
            return await call_next(ctx)
        except Exception as exc:
            logger.exception(
                "Elicitation for '%s' failed; denying the call", tool_name
            )
            return _refusal(
                f"{tool_name}: could not collect a confirmation "
                f"({type(exc).__name__}), so nothing was executed."
            )

        approved = (
            isinstance(result, AcceptedElicitation) and result.data.approved
        )

        if not approved:
            logger.info(
                "Confirmation for '%s' was not granted (request %s); "
                "returning an error result",
                tool_name,
                ctx.request_id,
            )
            return _refusal(DECLINED_MESSAGE.format(tool=tool_name))

        logger.info(
            "Confirmation for '%s' granted (request %s); executing",
            tool_name,
            ctx.request_id,
        )

        return await call_next(ctx)
