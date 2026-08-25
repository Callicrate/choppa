"""Exception classes for choppa."""

from __future__ import annotations


class RemoteError(RuntimeError):
    """Base exception for remote execution errors."""


class RemoteProtocolError(RemoteError):
    """Raised when the remote response does not match Choppa's protocol."""


class RemoteOutputTruncated(RemoteProtocolError):
    """Raised when Databricks returns only part of the command output."""

    def __init__(self, output: str) -> None:
        self.output = output
        super().__init__(
            "Databricks truncated the command output before Choppa could recover the result. "
            "Reduce stdout or the return value size."
        )


class RemoteArgumentsTooLarge(RemoteError):
    """Raised when serialized arguments exceed the configured limit."""

    def __init__(self, *, payload_name: str, payload_bytes: int, argument_size_max: int) -> None:
        self.payload_name = payload_name
        self.payload_bytes = payload_bytes
        self.argument_size_max = argument_size_max
        super().__init__(
            f"Serialized {payload_name} are {payload_bytes} bytes; the configured limit is {argument_size_max} bytes."
        )


class RemoteResultTooLarge(RemoteError):
    """Raised when a serialized result exceeds the configured limit."""

    def __init__(self, *, result_bytes: int, result_size_max: int) -> None:
        self.result_bytes = result_bytes
        self.result_size_max = result_size_max
        super().__init__(
            f"Remote result is {result_bytes} serialized bytes; the configured limit is {result_size_max} bytes."
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
