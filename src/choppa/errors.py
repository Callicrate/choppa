"""Exception classes for choppa."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from choppa.artifacts import ArtifactRef


class RemoteError(RuntimeError):
    """Base exception for remote execution errors."""

    pass


class ArtifactDirNotConfiguredError(RemoteError):
    """Raised when artifact storage is needed but artifact_dir was not configured."""

    def __init__(self, operation: str) -> None:
        super().__init__(
            f"Cannot {operation}: artifact_dir is not configured.\n"
            "Set artifact_dir when creating Choppa:\n"
            "  choppa = Choppa(cluster_id='...', artifact_dir='/Workspace/Users/you/artifacts')"
        )


class RemoteExecutionFailed(RemoteError):
    """Raised when remote code execution fails."""

    def __init__(self, *, message: str, traceback: str | None, output: str) -> None:
        self.remote_message = message
        self.remote_traceback = traceback
        self.output = output
        pretty = message
        if traceback:
            pretty += "\n\nRemote traceback:\n" + traceback
        pretty += "\n\nFull remote output:\n" + output
        super().__init__(pretty)


class RemoteResultTooLargeError(RemoteError):
    """
    Raised when @choppa.remote result exceeds result_size_max.

    The result is spilled to artifacts and available via `self.artifact`.
    Only raised when result_size_max is set (not None).
    """

    def __init__(
        self,
        *,
        artifact: ArtifactRef,
        inline_bytes: int,
        result_size_max: int,
    ) -> None:
        self.artifact = artifact
        self.inline_bytes = inline_bytes
        self.result_size_max = result_size_max
        super().__init__(
            "Remote return value was too large to send inline.\n"
            f"- inline bytes: {inline_bytes}\n"
            f"- result_size_max: {result_size_max}\n"
            f"- stored artifact: {artifact.path} (bytes={artifact.artifact_bytes})\n\n"
            "What now:\n"
            "  • If you want to keep chaining remotely, pass this ArtifactRef into another @choppa.remote/@choppa.artifact function.\n"
            "    (Arguments that are ArtifactRef get auto-loaded on the cluster.)\n"
            "  • If you want it locally, call choppa.dereference(e.artifact)\n"
            "  • To always return data inline (no size limit), set result_size_max=None when creating Choppa.\n"
            "  • If you expect big outputs often, use @choppa.artifact (sync) or @choppa.submit (async)."
        )
