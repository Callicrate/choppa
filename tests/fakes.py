"""Databricks SDK fakes for offline protocol tests."""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import timedelta
from io import StringIO
from typing import Any

from databricks.sdk.service import compute


@dataclass(frozen=True)
class ExecutionEvent:
    """One fake Command Execution operation."""

    operation: str
    cluster_id: str
    context_id: str | None = None


@dataclass
class FakeCommandExecution:
    """Run generated commands locally while recording Databricks routing."""

    workspace_name: str
    events: list[ExecutionEvent] = field(default_factory=list)
    truncate_next: bool = False
    omit_context_id: bool = False
    response_override: str | None = None
    execute_error: Exception | None = None
    destroy_error: Exception | None = None

    def create_and_wait(
        self,
        *,
        cluster_id: str | None = None,
        language: compute.Language | None = None,
        timeout: timedelta = timedelta(minutes=20),
    ) -> compute.ContextStatusResponse:
        del language, timeout
        assert cluster_id is not None
        self.events.append(ExecutionEvent("create", cluster_id))
        context_id = None if self.omit_context_id else f"{self.workspace_name}-context-{len(self.events)}"
        return compute.ContextStatusResponse(id=context_id)

    def execute_and_wait(
        self,
        *,
        cluster_id: str | None = None,
        command: str | None = None,
        context_id: str | None = None,
        language: compute.Language | None = None,
        timeout: timedelta = timedelta(minutes=20),
    ) -> compute.CommandStatusResponse:
        del language, timeout
        assert cluster_id is not None
        assert command is not None
        self.events.append(ExecutionEvent("execute", cluster_id, context_id))
        if self.execute_error is not None:
            raise self.execute_error

        if self.response_override is not None:
            output = self.response_override
            self.response_override = None
        else:
            captured = StringIO()
            with redirect_stdout(captured):
                exec(command, {})
            output = captured.getvalue()

        truncated = self.truncate_next
        self.truncate_next = False
        return compute.CommandStatusResponse(results=compute.Results(data=output, truncated=truncated))

    def destroy(self, *, cluster_id: str, context_id: str) -> None:
        self.events.append(ExecutionEvent("destroy", cluster_id, context_id))
        if self.destroy_error is not None:
            raise self.destroy_error


@dataclass
class FakeClusters:
    """Small cluster lifecycle fake."""

    state: compute.State = compute.State.RUNNING
    events: list[tuple[str, str]] = field(default_factory=list)

    def get(self, cluster_id: str) -> compute.ClusterDetails:
        self.events.append(("get", cluster_id))
        return compute.ClusterDetails(cluster_id=cluster_id, state=self.state)

    def start_and_wait(self, cluster_id: str) -> compute.ClusterDetails:
        self.events.append(("start", cluster_id))
        self.state = compute.State.RUNNING
        return compute.ClusterDetails(cluster_id=cluster_id, state=self.state)

    def wait_get_cluster_running(self, cluster_id: str) -> compute.ClusterDetails:
        self.events.append(("wait", cluster_id))
        self.state = compute.State.RUNNING
        return compute.ClusterDetails(cluster_id=cluster_id, state=self.state)


@dataclass
class FakeWorkspace:
    """WorkspaceClient-shaped fake with command and cluster services."""

    name: str = "workspace"
    command_execution: FakeCommandExecution = field(init=False)
    clusters: FakeClusters = field(default_factory=FakeClusters)

    def __post_init__(self) -> None:
        self.command_execution = FakeCommandExecution(self.name)


def operations(fake: FakeWorkspace, operation: str) -> list[ExecutionEvent]:
    """Return recorded command events matching an operation."""
    return [event for event in fake.command_execution.events if event.operation == operation]


def event_dicts(fake: FakeWorkspace) -> list[dict[str, Any]]:
    """Return serializable events for assertion diagnostics."""
    return [
        {
            "operation": event.operation,
            "cluster_id": event.cluster_id,
            "context_id": event.context_id,
        }
        for event in fake.command_execution.events
    ]
