"""Exception classes for choppa."""

from __future__ import annotations


class RemoteError(RuntimeError):
    """Base exception for remote execution errors."""

    pass


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
