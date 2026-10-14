


import asyncio
import time
from types import SimpleNamespace


import pytest
from mcp.server.elicitation import render_elicitation_schema


import confirmation
from confirmation import (
    ConfirmationMiddleware,
    ConfirmationResponse,
    ConfirmationSettings,
    build_prompt,
    supports_form_elicitation,
)


def make_session(
    form: bool | None = True,
    url: bool | None = None,
    elicit_result=None,
    elicit_error: Exception | None = None,
    never_answers: bool = False,
):
    """A stand-in for ServerSession that records elicitation calls."""

    calls: list[dict] = []

    async def elicit_form(message, requested_schema, related_request_id=None):
        calls.append(
            {
                "message": message,
                "schema": requested_schema,
                "related_request_id": related_request_id,
            }
        )

        if never_answers:
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

        if elicit_error is not None:
            raise elicit_error

        return elicit_result

    elicitation = None
    if form is not None or url is not None:
        elicitation = SimpleNamespace(
            form=SimpleNamespace() if form else None,
            url=SimpleNamespace() if url else None,
        )

    session = SimpleNamespace(
        client_capabilities=SimpleNamespace(elicitation=elicitation),
        elicit_form=elicit_form,
        calls=calls,
    )

    return session


def make_ctx(session, method: str = "tools/call", params=None, request_id="req-1"):
    return SimpleNamespace(
        method=method,
        params=params if params is not None else {},
        request_id=request_id,
        session=session,
    )


async def run_middleware(middleware, ctx):
    """Run the middleware and report whether the tool handler was reached."""

    reached = []

    async def call_next(ctx):
        reached.append(ctx.params.get("name"))
        return {"ok": True}

    result = await middleware(ctx, call_next)

    return result, reached


def approved():
    return SimpleNamespace(
        action="accept",
        content={"approved": True},
    )


def rejected():
    return SimpleNamespace(action="accept", content={"approved": False})


def call_params(name: str, **arguments):
    return {"name": name, "arguments": arguments}


READ_ONLY_TOOLS = [
    "list_databases",
    "database_info",
    "list_schemas",
    "list_tables",
    "describe_table",
    "read_table",
    "query",
    "count_rows",
    "table_stats",
]


class TestGuardedToolSet:
    def test_every_guarded_name_is_a_registered_tool(self):
        import server

        registered = {tool.name for tool in asyncio.run(server.mcp.list_tools())}

        assert confirmation.MUTATING_TOOLS <= registered

    def test_destructive_and_anonymizing_sets_are_subsets(self):
        assert confirmation.DESTRUCTIVE_TOOLS <= confirmation.MUTATING_TOOLS
        assert confirmation.ANONYMIZING_TOOLS <= confirmation.MUTATING_TOOLS

    def test_dml_and_ddl_families_are_covered(self):
        assert {
            "insert_row",
            "insert_rows",
            "update_rows",
            "delete_rows",
            "upsert_row",
        } <= confirmation.MUTATING_TOOLS

        assert {
            "create_table",
            "delete_table",
            "alter_table",
            "create_database",
            "delete_database",
        } <= confirmation.MUTATING_TOOLS

    def test_read_tools_are_not_guarded(self):
        assert not confirmation.MUTATING_TOOLS & set(READ_ONLY_TOOLS)

    def test_no_read_only_tool_is_marked_destructive(self):
        assert not confirmation.DESTRUCTIVE_TOOLS & set(READ_ONLY_TOOLS)

    @pytest.mark.parametrize("name", sorted(READ_ONLY_TOOLS))
    def test_read_only_tool_passes_through_without_a_prompt(self, name):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(session, params=call_params(name, database="postgres"))

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == [name]
        assert result == {"ok": True}
        assert session.calls == []


class TestSettings:
    def test_confirmation_is_on_by_default(self, monkeypatch):
        monkeypatch.delenv(confirmation.ENV_CONFIRM, raising=False)

        assert ConfirmationSettings.from_env().enabled is True

    @pytest.mark.parametrize("value", ["0", "false", "off", "no", ""])
    def test_disabling_via_env(self, monkeypatch, value):
        monkeypatch.setenv(confirmation.ENV_CONFIRM, value)

        assert ConfirmationSettings.from_env().enabled is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
    def test_enabling_via_env(self, monkeypatch, value):
        monkeypatch.setenv(confirmation.ENV_CONFIRM, value)

        assert ConfirmationSettings.from_env().enabled is True

    def test_garbage_value_falls_back_to_the_default(self, monkeypatch):
        monkeypatch.setenv(confirmation.ENV_CONFIRM, "maybe")

        assert ConfirmationSettings.from_env().enabled is True

    def test_allowlist_is_parsed_and_trims_whitespace(self, monkeypatch):
        monkeypatch.setenv(
            confirmation.ENV_ALLOWLIST, " insert_row , delete_table ,, "
        )

        settings = ConfirmationSettings.from_env()

        assert settings.allowlist == {"insert_row", "delete_table"}
        assert settings.needs_confirmation("insert_row") is False
        assert settings.needs_confirmation("delete_rows") is True

    def test_allowlist_overrides_a_disabled_gate(self):
        settings = ConfirmationSettings(
            enabled=True, allowlist=frozenset({"insert_row"})
        )

        assert settings.needs_confirmation("insert_row") is False

    def test_disabled_gate_needs_no_confirmation(self):
        settings = ConfirmationSettings(enabled=False)

        assert settings.needs_confirmation("delete_table") is False

    def test_unsupported_clients_are_denied_by_default(self, monkeypatch):
        monkeypatch.delenv(
            confirmation.ENV_ALLOW_NO_ELICITATION, raising=False
        )

        assert ConfirmationSettings.from_env().allow_without_elicitation is False

    def test_unsupported_clients_can_be_allowed_explicitly(self, monkeypatch):
        monkeypatch.setenv(confirmation.ENV_ALLOW_NO_ELICITATION, "1")

        assert ConfirmationSettings.from_env().allow_without_elicitation is True


class TestCapabilityDetection:
    def test_form_capable_client(self):
        assert supports_form_elicitation(make_session(form=True)) is True

    def test_client_without_any_capabilities(self):
        session = make_session(form=None)
        session.client_capabilities = None

        assert supports_form_elicitation(session) is False

    def test_client_with_no_elicitation_capability(self):
        session = make_session(form=None, url=None)
        session.client_capabilities = SimpleNamespace(elicitation=None)

        assert supports_form_elicitation(session) is False

    def test_url_only_client_cannot_answer_a_form(self):
        assert supports_form_elicitation(make_session(form=False, url=True)) is False

    def test_legacy_empty_elicitation_object_counts_as_form(self):
        assert supports_form_elicitation(make_session(form=False, url=False)) is True


class TestConfirmationGate:
    def test_mutation_is_blocked_until_approved(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(
            session,
            params=call_params(
                "delete_rows",
                database="shop",
                table="customers",
                where={"id": 1},
            ),
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["delete_rows"]
        assert result == {"ok": True}
        assert len(session.calls) == 1

    def test_the_prompt_shows_the_operation_details(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(
            session,
            params=call_params(
                "delete_rows",
                database="shop",
                table="customers",
                where={"id": 1},
            ),
        )

        asyncio.run(run_middleware(middleware, ctx))

        message = session.calls[0]["message"]

        assert "delete_rows" in message
        assert "shop" in message
        assert "public.customers" in message
        assert "id = 1" in message
        assert "DESTRUCTIVE" in message

    def test_the_prompt_carries_a_valid_elicitation_schema(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(session, params=call_params("insert_row", database="shop"))

        asyncio.run(run_middleware(middleware, ctx))

        schema = session.calls[0]["schema"]

        assert schema == render_elicitation_schema(ConfirmationResponse)

    def test_the_prompt_is_related_to_the_originating_request(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(
            session, params=call_params("insert_row", database="shop"),
            request_id="req-42",
        )

        asyncio.run(run_middleware(middleware, ctx))

        assert session.calls[0]["related_request_id"] == "req-42"

    def test_declining_returns_an_error_and_never_runs_the_tool(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=rejected())
        ctx = make_ctx(
            session, params=call_params("delete_table", database="shop", table="t")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == []
        assert result.is_error is True
        assert "declined" in result.content[0].text

    def test_an_empty_answer_is_treated_as_a_decline(self):
        middleware = ConfirmationMiddleware()
        session = make_session(
            elicit_result=SimpleNamespace(action="accept", content={})
        )
        ctx = make_ctx(
            session, params=call_params("delete_table", database="shop", table="t")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == []
        assert result.is_error is True

    def test_declining_the_prompt_itself_runs_nothing(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=SimpleNamespace(action="decline"))
        ctx = make_ctx(
            session, params=call_params("delete_table", database="shop", table="t")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == []
        assert result.is_error is True

    def test_a_failing_prompt_fails_closed(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_error=RuntimeError("channel closed"))
        ctx = make_ctx(
            session, params=call_params("insert_row", database="shop", table="t")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == []
        assert result.is_error is True
        assert "RuntimeError" in result.content[0].text

    def test_an_unsupported_client_is_denied_by_default(self):
        middleware = ConfirmationMiddleware()
        session = make_session(form=False, url=False)
        session.client_capabilities = SimpleNamespace(elicitation=None)
        ctx = make_ctx(
            session, params=call_params("insert_row", database="shop", table="t")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == []
        assert result.is_error is True
        assert "does not support elicitation" in result.content[0].text

    def test_a_url_only_client_is_denied(self):
        middleware = ConfirmationMiddleware()
        session = make_session(form=False, url=True)
        ctx = make_ctx(
            session, params=call_params("insert_row", database="shop", table="t")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == []
        assert result.is_error is True

    def test_an_unsupported_client_can_be_allowed_explicitly(self):
        middleware = ConfirmationMiddleware(
            ConfirmationSettings(allow_without_elicitation=True)
        )
        session = make_session(form=False, url=False)
        session.client_capabilities = SimpleNamespace(elicitation=None)
        ctx = make_ctx(
            session, params=call_params("insert_row", database="shop", table="t")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["insert_row"]
        assert result == {"ok": True}

    def test_a_disabled_gate_passes_straight_through(self):
        middleware = ConfirmationMiddleware(ConfirmationSettings(enabled=False))
        session = make_session(form=False, url=False)
        session.client_capabilities = SimpleNamespace(elicitation=None)
        ctx = make_ctx(
            session, params=call_params("delete_database", database="prod")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["delete_database"]
        assert result == {"ok": True}
        assert session.calls == []

    def test_an_allowlisted_tool_skips_the_prompt(self):
        middleware = ConfirmationMiddleware(
            ConfirmationSettings(allowlist=frozenset({"insert_row"}))
        )
        session = make_session(elicit_result=approved())
        ctx = make_ctx(
            session, params=call_params("insert_row", database="shop", table="t")
        )

        _, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["insert_row"]
        assert session.calls == []

    @pytest.mark.parametrize(
        "method", ["tools/list", "resources/list", "ping", "initialize"]
    )
    def test_other_methods_are_never_gated(self, method):
        middleware = ConfirmationMiddleware()
        session = make_session(form=False, url=False)
        session.client_capabilities = SimpleNamespace(elicitation=None)
        ctx = make_ctx(session, method=method, params={})

        _, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == [None]
        assert session.calls == []

    def test_a_notification_carrying_a_mutating_name_is_not_gated(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(
            session,
            method="notifications/message",
            params=call_params("delete_database", database="prod"),
        )

        _, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["delete_database"]
        assert session.calls == []

    def test_a_request_without_a_name_is_not_gated(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(session, params={"arguments": {}})

        _, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == [None]
        assert session.calls == []

    def test_missing_arguments_do_not_break_the_prompt(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(session, params={"name": "insert_row"})

        _, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["insert_row"]
        assert "insert_row" in session.calls[0]["message"]

    def test_non_dict_arguments_do_not_break_the_prompt(self):
        middleware = ConfirmationMiddleware()
        session = make_session(elicit_result=approved())
        ctx = make_ctx(
            session, params={"name": "insert_row", "arguments": ["oops"]}
        )

        _, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["insert_row"]


class TestConfirmationTimeout:
    """A client that accepts the request and never answers must not hang."""

    def test_a_silent_client_is_cut_off_and_denied(self):
        middleware = ConfirmationMiddleware(
            ConfirmationSettings(timeout_seconds=0.2)
        )
        session = make_session(never_answers=True)
        ctx = make_ctx(
            session, params=call_params("delete_database", database="prod")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == []
        assert result.is_error is True
        assert "no confirmation was received" in result.content[0].text

    def test_the_timeout_message_names_the_escape_hatch(self):
        middleware = ConfirmationMiddleware(
            ConfirmationSettings(timeout_seconds=0.2)
        )
        session = make_session(never_answers=True)
        ctx = make_ctx(
            session, params=call_params("delete_database", database="prod")
        )

        result, _ = asyncio.run(run_middleware(middleware, ctx))

        assert confirmation.ENV_ALLOW_NO_ELICITATION in result.content[0].text
        assert confirmation.ENV_TIMEOUT in result.content[0].text

    def test_a_silent_client_does_not_hang_the_delete(self):
        """Regression: the tool call used to block forever."""

        middleware = ConfirmationMiddleware(
            ConfirmationSettings(timeout_seconds=0.2)
        )
        session = make_session(never_answers=True)
        ctx = make_ctx(
            session, params=call_params("delete_table", database="d", table="t")
        )

        started = time.monotonic()
        result, reached = asyncio.run(run_middleware(middleware, ctx))
        elapsed = time.monotonic() - started

        assert reached == []
        assert result.is_error is True
        assert elapsed < 3

    def test_a_silent_client_can_be_allowed_to_proceed(self):
        middleware = ConfirmationMiddleware(
            ConfirmationSettings(
                timeout_seconds=0.2, allow_without_elicitation=True
            )
        )
        session = make_session(never_answers=True)
        ctx = make_ctx(
            session, params=call_params("delete_database", database="prod")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["delete_database"]
        assert result == {"ok": True}

    def test_a_prompt_that_is_answered_in_time_still_works(self):
        middleware = ConfirmationMiddleware(
            ConfirmationSettings(timeout_seconds=10)
        )
        session = make_session(elicit_result=approved())
        ctx = make_ctx(
            session, params=call_params("insert_row", database="shop", table="t")
        )

        result, reached = asyncio.run(run_middleware(middleware, ctx))

        assert reached == ["insert_row"]
        assert result == {"ok": True}


class TestTimeoutSetting:
    def test_default_timeout_is_bounded(self, monkeypatch):
        monkeypatch.delenv(confirmation.ENV_TIMEOUT, raising=False)

        assert ConfirmationSettings.from_env().timeout_seconds > 0

    def test_timeout_is_configurable(self, monkeypatch):
        monkeypatch.setenv(confirmation.ENV_TIMEOUT, "5")

        assert ConfirmationSettings.from_env().timeout_seconds == 5.0

    @pytest.mark.parametrize("value", ["abc", "", "-1", "0"])
    def test_a_bad_timeout_falls_back_to_the_default(self, monkeypatch, value):
        monkeypatch.setenv(confirmation.ENV_TIMEOUT, value)

        settings = ConfirmationSettings.from_env()

        assert settings.timeout_seconds == confirmation.DEFAULT_TIMEOUT_SECONDS

    def test_a_fractional_timeout_is_allowed(self, monkeypatch):
        monkeypatch.setenv(confirmation.ENV_TIMEOUT, "0.5")

        assert ConfirmationSettings.from_env().timeout_seconds == 0.5


class TestPromptRendering:
    @pytest.mark.parametrize("name", sorted(confirmation.MUTATING_TOOLS))
    def test_every_guarded_tool_renders_a_prompt(self, name):
        prompt = build_prompt(name, {"database": "shop", "table": "t"})

        assert name in prompt
        assert "approval required" in prompt

    def test_an_unknown_tool_still_renders(self):
        prompt = build_prompt("some_future_tool", {"database": "shop"})

        assert "some_future_tool" in prompt
        assert "shop" in prompt

    def test_long_values_are_truncated(self):
        prompt = build_prompt("insert_row", {"data": {"blob": "x" * 5000}})

        assert "…" in prompt
        assert len(prompt) < 2000

    def test_many_columns_are_truncated_with_a_count(self):
        prompt = build_prompt(
            "update_rows",
            {"updates": {f"c{i}": i for i in range(40)}},
        )

        assert "and 30 more" in prompt

    def test_many_rows_are_truncated_with_a_count(self):
        prompt = build_prompt(
            "insert_rows", {"rows": [{"a": i} for i in range(40)]}
        )

        assert "and 30 more rows" in prompt

    def test_delete_table_warns_about_data_loss(self):
        prompt = build_prompt("delete_table", {"database": "s", "table": "t"})

        assert "DROP TABLE IF EXISTS" in prompt
        assert "DESTRUCTIVE" in prompt

    def test_anonymizing_tools_say_pii_is_masked(self):
        prompt = build_prompt(
            "anonymize_and_insert", {"data": {"email": "a@b.com"}}
        )

        assert "masked" in prompt

    def test_upsert_reports_the_conflict_column(self):
        prompt = build_prompt(
            "upsert_row", {"data": {"id": 1}, "conflict_column": "id"}
        )

        assert "id" in prompt

    def test_alter_table_reports_the_operation(self):
        prompt = build_prompt(
            "alter_table",
            {
                "operation": "add_column",
                "column": "age",
                "column_type": "INTEGER",
            },
        )

        assert "add_column" in prompt
        assert "age" in prompt
        assert "INTEGER" in prompt

    def test_create_table_lists_columns(self):
        prompt = build_prompt(
            "create_table", {"columns": {"id": "SERIAL", "name": "VARCHAR(10)"}}
        )

        assert "id = SERIAL" in prompt
        assert "name = VARCHAR(10)" in prompt


class TestResponseModel:
    def test_defaults_to_not_approved(self):
        assert ConfirmationResponse().approved is False

    def test_accepts_an_explicit_yes(self):
        assert ConfirmationResponse(approved=True).approved is True
