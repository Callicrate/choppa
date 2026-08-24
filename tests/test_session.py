"""Decorator and execution-session behavior tests."""

from __future__ import annotations

from typing import cast

import pytest
from databricks.sdk import WorkspaceClient

from choppa import Choppa, RemoteOutputTruncated, RemoteProtocolError
from choppa.codegen import RemoteFunction
from choppa.session import RemoteSession
from tests.fakes import FakeWorkspace, event_dicts, operations


def _client(cluster_id: str, fake: FakeWorkspace, *, result_size_max: int = 256_000) -> Choppa:
    return Choppa(
        cluster_id=cluster_id,
        result_size_max=result_size_max,
        w=cast(WorkspaceClient, fake),
    )


class TestRemoteDecorator:
    """Decorator calls should route through the owning Choppa instance."""

    def test_direct_call_uses_one_context(self) -> None:
        fake = FakeWorkspace("one")
        client = _client("cluster-one", fake)

        @client.remote
        def add(a: int, b: int) -> int:
            return a + b

        assert add(1, 2) == 3
        assert [event.operation for event in fake.command_execution.events] == ["create", "execute", "destroy"]

    def test_session_reuses_one_context(self) -> None:
        fake = FakeWorkspace("one")
        client = _client("cluster-one", fake)

        @client.remote
        def double(value: int) -> int:
            return value * 2

        with client.session():
            assert double(5) == 10
            assert double(10) == 20

        assert len(operations(fake, "create")) == 1
        assert len(operations(fake, "execute")) == 2
        assert len(operations(fake, "destroy")) == 1

    def test_other_instance_opens_its_own_session(self) -> None:
        fake_a = FakeWorkspace("a")
        fake_b = FakeWorkspace("b")
        client_a = _client("cluster-a", fake_a)
        client_b = _client("cluster-b", fake_b)

        @client_a.remote
        def add_one(value: int) -> int:
            return value + 1

        @client_b.remote
        def subtract_one(value: int) -> int:
            return value - 1

        with client_a.session():
            assert subtract_one(10) == 9
            assert add_one(10) == 11

        assert [event.cluster_id for event in operations(fake_a, "execute")] == ["cluster-a"]
        assert [event.cluster_id for event in operations(fake_b, "execute")] == ["cluster-b"]

    def test_async_function_is_rejected_before_api_call(self) -> None:
        fake = FakeWorkspace()
        client = _client("cluster", fake)

        async def async_function() -> int:
            return 1

        with pytest.raises(TypeError, match="Async"):
            client.remote(async_function)
        assert fake.command_execution.events == []

    def test_closure_is_rejected_before_api_call(self) -> None:
        fake = FakeWorkspace()
        client = _client("cluster", fake)
        captured = 7

        def closure() -> int:
            return captured

        with pytest.raises(TypeError, match="captured"):
            client.remote(closure)
        assert fake.command_execution.events == []

    def test_stacked_choppa_decorators_are_rejected(self) -> None:
        fake = FakeWorkspace()
        client = _client("cluster", fake)

        @client.remote
        def value() -> int:
            return 1

        with pytest.raises(TypeError, match="stack"):
            client.remote(value)


class TestRemoteSession:
    """Session lifecycle and response failures should be deterministic."""

    def test_call_requires_enter(self) -> None:
        fake = FakeWorkspace()
        client = _client("cluster", fake)
        session = RemoteSession(client)
        remote: RemoteFunction[[], int] = RemoteFunction(name="value", source="def value(): return 1\n")
        with pytest.raises(RuntimeError, match="not initialized"):
            session.call(remote)

    def test_cluster_target_is_frozen_until_cleanup(self) -> None:
        fake = FakeWorkspace()
        client = _client("cluster-a", fake)

        @client.remote
        def value() -> int:
            return 1

        with client.session():
            client.set_cluster("cluster-b")
            assert value() == 1

        assert event_dicts(fake) == [
            {"operation": "create", "cluster_id": "cluster-a", "context_id": None},
            {
                "operation": "execute",
                "cluster_id": "cluster-a",
                "context_id": "workspace-context-1",
            },
            {
                "operation": "destroy",
                "cluster_id": "cluster-a",
                "context_id": "workspace-context-1",
            },
        ]

    def test_truncated_response_has_specific_error_and_cleans_up(self) -> None:
        fake = FakeWorkspace()
        fake.command_execution.truncate_next = True
        client = _client("cluster", fake)

        @client.remote
        def value() -> int:
            return 1

        with pytest.raises(RemoteOutputTruncated):
            value()
        assert len(operations(fake, "destroy")) == 1

    def test_execute_failure_cleans_up_context(self) -> None:
        fake = FakeWorkspace()
        fake.command_execution.execute_error = TimeoutError("command timed out")
        client = _client("cluster", fake)

        @client.remote
        def value() -> int:
            return 1

        with pytest.raises(TimeoutError, match="timed out"):
            value()
        assert len(operations(fake, "destroy")) == 1

    def test_missing_context_id_fails_before_token_is_set(self) -> None:
        fake = FakeWorkspace()
        fake.command_execution.omit_context_id = True
        client = _client("cluster", fake)
        with pytest.raises(RemoteProtocolError, match="context"), client.session():
            pass
        assert operations(fake, "execute") == []

    def test_session_cannot_be_entered_twice(self) -> None:
        fake = FakeWorkspace()
        client = _client("cluster", fake)
        with client.session() as session, pytest.raises(RuntimeError, match="already active"):
            session.__enter__()
        assert len(operations(fake, "create")) == 1
        assert len(operations(fake, "destroy")) == 1

    def test_destroy_failure_still_clears_local_state(self) -> None:
        fake = FakeWorkspace()
        client = _client("cluster", fake)
        session = client.session()
        session.__enter__()
        fake.command_execution.destroy_error = RuntimeError("cleanup failed")

        with pytest.raises(RuntimeError, match="cleanup failed"):
            session.__exit__(None, None, None)

        with pytest.raises(RuntimeError, match="not initialized"):
            remote: RemoteFunction[[], int] = RemoteFunction(name="value", source="def value(): return 1\n")
            session.call(remote)
