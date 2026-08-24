# Contributing to Choppa

Choppa is small by design.
Changes should preserve a narrow public API, fail clearly at local and remote
boundaries, and include tests for every changed contract.

## Table of Contents

- [Development Setup](#development-setup)
- [Offline Validation](#offline-validation)
- [Live Integration Tests](#live-integration-tests)
- [Pull Requests](#pull-requests)
- [Release Checklist](#release-checklist)

## Development Setup

Requirements:

- Python 3.10 through 3.12;
- [`uv`](https://docs.astral.sh/uv/); and
- no Databricks credentials for the default offline suite.

```bash
git clone https://github.com/Callicrate/choppa.git
cd choppa
uv sync --locked --extra dev
```

## Offline Validation

Run these checks before opening a pull request:

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run yamllint .github/workflows/ci.yml .yamllint.yml
uv run zizmor --pedantic .github/workflows/ci.yml
uv run pymarkdownlnt -d md013 scan README.md CONTRIBUTING.md SECURITY.md
uv run mypy src tests scripts
uv run pytest --cov=choppa --cov-branch --cov-fail-under=90
uv build
uv run twine check dist/*
```

The default suite uses SDK-shaped fakes and must not contact Databricks.
Tests that need a live workspace belong in `tests/test_integration.py` and must retain the explicit opt-in gate.

## Live Integration Tests

> Live tests can execute code and consume billable Databricks compute.
> Use only a disposable, non-production, running classic all-purpose cluster that you are authorized to use.

Set both variables so the action cannot be triggered by an ordinary developer profile:

```bash
export CHOPPA_RUN_INTEGRATION=1
export CHOPPA_TEST_CLUSTER_ID=0123-456789-example
uv run pytest -m integration tests/test_integration.py
```

The cluster ID must be passed through `CHOPPA_TEST_CLUSTER_ID`; tests must not discover a personal default cluster.
Never place workspace tokens, client secrets, or cluster credentials in the repository or test output.

## Pull Requests

- Keep changes focused and explain the user-visible contract being changed.
- Add positive, negative, and cleanup-path tests.
- Update `README.md` in the same change when behavior or public interfaces change.
- Do not weaken result-size, target-ownership, profile-isolation, or integration opt-in controls.
- Confirm the built wheel, not only the source checkout, passes a clean-install smoke test.
- Type-check the consumer fixture against the installed wheel.

## Release Checklist

Before publishing:

1. Confirm every CI job passes on the supported Python versions.
2. Run an explicitly authorized live smoke on disposable classic compute.
3. Verify the wheel version equals `choppa.__version__`.
4. Run `twine check`, `check-wheel-contents`, and `pip-audit`.
5. Add user-facing release notes from the committed diff.
6. Create a signed tag and matching GitHub release.
7. Publish through PyPI Trusted Publishing rather than a long-lived token.
