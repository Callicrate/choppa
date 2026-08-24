# Choppa

> **Get to da cluster.**

Run small, self-contained Python functions on a classic Databricks cluster from local code.

[![PyPI version](https://badge.fury.io/py/choppa.svg)](https://pypi.org/project/choppa/)
[![CI][ci-badge]][ci-workflow]
[![Python 3.10-3.12](https://img.shields.io/badge/python-3.10--3.12-3291B6.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-BB8ED0.svg)](./LICENSE)

Choppa is a synchronous convenience layer over the Databricks Command Execution API.
It transfers one function's source plus serialized arguments, executes them on
the cluster driver, and returns the result.

> Choppa is beta software with a deliberately narrow scope.
> It does not replace Databricks jobs, bundles, Databricks Connect, or production orchestration.

## Table of Contents

- [Supported Environment](#supported-environment)
- [Installation](#installation)
- [Configuration](#configuration)
- [Quickstart](#quickstart)
- [Sessions](#sessions)
- [Function Contract](#function-contract)
- [Results and Errors](#results-and-errors)
- [Security and Trust](#security-and-trust)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Supported Environment

Choppa currently supports:

- local Python 3.10 through 3.12;
- a **running classic all-purpose Databricks cluster**;
- Databricks authentication supported by `WorkspaceClient`;
- Python execution through the Databricks Command Execution API; and
- small arguments and return values that can be serialized with `cloudpickle`.

Command Execution does not support serverless compute.
See the [Databricks Command Execution documentation][command-execution].

The target cluster must already be running.
Choppa does not start billable compute automatically.
Calling `Choppa.ensure_cluster_running()` is an explicit operation and may incur Databricks charges.

For complex serialized values, use a local Python version compatible with the target Databricks Runtime.
Any modules imported by a remote function must also be installed on the cluster.

## Installation

```bash
python -m pip install choppa
```

The base installation includes `cloudpickle`, which every remote call requires locally.
The target cluster must also be able to import `cloudpickle`.

## Configuration

Configure Databricks unified authentication for
[AWS][unified-auth-aws], [Azure][unified-auth-azure], or
[Google Cloud][unified-auth-gcp] before using Choppa.
Authentication and cluster selection are separate: `WorkspaceClient` resolves
the workspace and credentials, while Choppa resolves the cluster ID.

Cluster selection uses this order:

1. The `cluster_id` passed to `Choppa(...)` or `choppa.set_cluster(...)`.
2. `DATABRICKS_CLUSTER_ID`.
3. The `cluster_id` in the profile named by `DATABRICKS_CONFIG_PROFILE`.
4. The `cluster_id` in the literal `DEFAULT` profile when no profile is selected.

`DATABRICKS_CONFIG_FILE` can point to a configuration file other than `~/.databrickscfg`.
When an explicit profile is selected, Choppa never borrows a cluster ID from `DEFAULT`.

Example configuration:

```ini
[research]
host = https://example.cloud.databricks.com
cluster_id = 0123-456789-example
```

```bash
export DATABRICKS_CONFIG_PROFILE=research
```

## Quickstart

```python
import choppa


@choppa.remote
def add(a: int, b: int) -> int:
    return a + b


result = add(1, 2)
assert result == 3
```

Each call creates and destroys one Databricks execution context unless it runs inside a session.

Use `Choppa` instances when targeting more than one cluster or workspace:

```python
from databricks.sdk import WorkspaceClient

from choppa import Choppa

analytics = Choppa(
    cluster_id="0123-456789-analytics",
    w=WorkspaceClient(profile="analytics"),
)


@analytics.remote
def square(value: int) -> int:
    return value * value
```

Sessions are bound to their owning `Choppa` instance, so nested calls cannot silently cross targets.

## Sessions

Reuse one execution context for a group of synchronous calls:

```python
import choppa


@choppa.remote
def increment(value: int) -> int:
    return value + 1


with choppa.session():
    results = [increment(value) for value in range(100)]
```

Changing the cluster on a `Choppa` instance takes effect after its active session ends.
The session retains the client, cluster ID, and context with which it started so cleanup cannot drift to another target.

## Function Contract

Remote functions must:

- be synchronous functions defined in a normal `.py` file;
- be self-contained apart from their arguments and imports available on the cluster;
- put required imports inside the function body;
- avoid closures and module globals; and
- return a trusted value that `cloudpickle` can serialize.

Choppa rejects async functions and closures during decoration.
It strips ordinary single-line and multiline decorators using Python's AST before sending source to the cluster.

```python
import choppa


@choppa.remote
def vector_length(values: list[float]) -> float:
    from math import sqrt

    return sqrt(sum(value * value for value in values))
```

## Results and Errors

The default serialized limit is 256,000 bytes for each argument collection and
for the result.
Use an instance to choose a smaller or larger bounded limit:

```python
from choppa import Choppa

client = Choppa(argument_size_max=128_000, result_size_max=512_000)
```

Relevant exceptions include:

- `RemoteExecutionFailed` for an exception raised by the remote function;
- `RemoteArgumentsTooLarge` when positional or keyword arguments exceed `argument_size_max`;
- `RemoteResultTooLarge` when the serialized result exceeds `result_size_max`;
- `RemoteOutputTruncated` when Databricks returns only partial command output; and
- `RemoteProtocolError` for malformed or incomplete protocol output.

Choppa is designed for small return values.
Store large data in a governed table or volume and return a small identifier instead.
Excessive function stdout can also make Databricks truncate the command response.

## Security and Trust

Choppa intentionally performs remote code execution.
It sends function source and pickled arguments to the selected cluster, then unpickles the result on the local machine.

Use Choppa only when you fully trust:

- the selected Databricks workspace and cluster;
- the remote function and every dependency it imports; and
- every returned object and its custom serialization behavior.

`pickle` and `cloudpickle` can execute code while loading data.
Choppa bounds compressed result expansion, but a trusted-cluster requirement remains fundamental.
Do not use Choppa as a sandbox for untrusted code or untrusted data.

Credentials remain under the Databricks SDK's unified-authentication system.
Do not place tokens or secrets in source code, function arguments, logs, or committed configuration files.

See [SECURITY.md](./SECURITY.md) for vulnerability reporting and supported security boundaries.

## Development

Install the locked development environment and run the release gates:

```bash
uv sync --locked --extra dev
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run yamllint .github/workflows/ci.yml .yamllint.yml
uv run zizmor --pedantic .github/workflows/ci.yml
uv run pymarkdownlnt -d md013 scan README.md CONTRIBUTING.md SECURITY.md
uv run mypy src tests scripts
uv run pytest --cov=choppa --cov-branch --cov-fail-under=90
uv build
```

Live integration tests are opt-in and require a disposable running classic cluster.
See [CONTRIBUTING.md](./CONTRIBUTING.md) for the safety gate and exact command.

## Contributing

Bug reports and focused pull requests are welcome.
Read [CONTRIBUTING.md](./CONTRIBUTING.md) before running any live integration test.

## License

Choppa is available under the [MIT License](./LICENSE).

[ci-badge]: https://github.com/Callicrate/choppa/actions/workflows/ci.yml/badge.svg
[ci-workflow]: https://github.com/Callicrate/choppa/actions/workflows/ci.yml
[command-execution]: https://databricks-sdk-py.readthedocs.io/en/stable/workspace/compute/command_execution.html
[unified-auth-aws]: https://docs.databricks.com/aws/en/dev-tools/auth/unified-auth
[unified-auth-azure]: https://learn.microsoft.com/en-us/azure/databricks/dev-tools/auth/unified-auth
[unified-auth-gcp]: https://docs.databricks.com/gcp/en/dev-tools/auth/unified-auth
