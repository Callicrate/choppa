"""
Choppa: Get to da cluster!

Remote function execution for Databricks clusters via the Command Execution API.
"""

from choppa._version import __version__
from choppa.choppa import Choppa
from choppa.codegen import RemoteFunction
from choppa.errors import RemoteError, RemoteExecutionFailed
from choppa.session import RemoteSession

__all__ = [
    "Choppa",
    "RemoteError",
    "RemoteExecutionFailed",
    "RemoteFunction",
    "RemoteSession",
    "__version__",
]
