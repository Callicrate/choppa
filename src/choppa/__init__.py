"""
Choppa: Get to da cluster!

Remote function execution for Databricks clusters via the Command Execution API.
"""

from choppa._version import __version__
from choppa.artifacts import ArtifactRef
from choppa.choppa import Choppa
from choppa.codegen import RemoteFunction
from choppa.errors import ArtifactDirNotConfiguredError, RemoteError, RemoteExecutionFailed, RemoteResultTooLargeError
from choppa.session import RemoteHandle, RemoteSession

__all__ = [
    "ArtifactDirNotConfiguredError",
    "ArtifactRef",
    "Choppa",
    "RemoteError",
    "RemoteExecutionFailed",
    "RemoteFunction",
    "RemoteHandle",
    "RemoteResultTooLargeError",
    "RemoteSession",
    "__version__",
]
