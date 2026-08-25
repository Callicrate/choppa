# Security Policy

Choppa transfers and executes Python source and serialized data across a
Databricks trust boundary.
Security reports are welcome, especially for target confusion, credential
exposure, unsafe cleanup, result-protocol bypasses, and unexpected local code
execution.

## Supported Versions

| Version | Supported |
|---|---|
| 0.2.1.x | Yes |
| 0.2.0 and earlier | No |

Only the latest released patch receives security fixes.

## Reporting a Vulnerability

Use GitHub's private vulnerability-reporting flow for this repository when it is available.
If private reporting is unavailable, open a minimal issue requesting a private
contact channel and do not include exploit details, credentials, workspace
identifiers, or customer data.

Include:

- the affected Choppa version;
- the local Python and Databricks Runtime versions;
- whether the issue occurs before or after a workspace call;
- a minimal reproduction using fake identifiers; and
- the expected and observed security boundary.

Do not test against clusters, workspaces, or data you do not own or have explicit authorization to use.

## Trust Boundary

Choppa is not a sandbox.
The local process fully trusts the configured Databricks cluster because returned values are loaded with `cloudpickle`.
A compromised cluster or malicious remote dependency can therefore influence
local code execution during deserialization.

Choppa applies argument-size, result-size, and bounded-decompression checks,
but those controls do not make untrusted pickle safe.
Use the package only with trusted code, dependencies, workspaces, clusters, and return values.

## Credentials

Choppa delegates authentication to the Databricks SDK.
Never include tokens, passwords, client secrets, private keys, or certificates
in source code, function arguments, logs, issues, or pull requests.
