"""Generated-code and result-protocol tests."""

from __future__ import annotations

import base64
import json
import zlib
from contextlib import redirect_stdout
from io import StringIO
from typing import Any

import cloudpickle  # type: ignore[import-untyped]
import pytest

from choppa import RemoteArgumentsTooLarge, RemoteExecutionFailed, RemoteProtocolError, RemoteResultTooLarge
from choppa._internal import _strip_leading_decorators
from choppa.codegen import _CHOPPA_META_MARKER, RemoteFunction, _build_invoke_code
from choppa.session import _find_meta, _interpret_meta


def _execute_generated(code: str) -> str:
    captured = StringIO()
    with redirect_stdout(captured):
        exec(code, {})
    return captured.getvalue()


def _remote_function(name: str, source: str) -> RemoteFunction[Any, Any]:
    return RemoteFunction(name=name, source=source)


class TestFunctionSource:
    """Function extraction should accept common definitions and reject ambiguity."""

    def test_strips_single_line_decorator(self) -> None:
        assert _strip_leading_decorators("@decorator\ndef foo():\n    return 1\n").startswith("def foo")

    def test_strips_multiline_decorator(self) -> None:
        source = "@decorator(\n    enabled=True,\n)\ndef foo():\n    return 1\n"
        assert _strip_leading_decorators(source) == "def foo():\n    return 1\n"

    def test_rejects_multiple_definitions(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            _strip_leading_decorators("def one(): pass\ndef two(): pass\n")

    def test_rejects_invalid_source(self) -> None:
        with pytest.raises(ValueError, match="valid Python"):
            _strip_leading_decorators("def broken(:\n")


class TestGeneratedInvocation:
    """The generated protocol should preserve values and failures."""

    def test_round_trip(self) -> None:
        remote = _remote_function("add", "def add(a, b):\n    return a + b\n")
        output = _execute_generated(
            _build_invoke_code(
                remote_def=remote,
                args=(1, 2),
                kwargs={},
                argument_size_max=256_000,
                result_size_max=256_000,
            )
        )
        assert _interpret_meta(_find_meta(output), output, result_size_max=256_000) == 3

    def test_kwargs_round_trip(self) -> None:
        remote = _remote_function("greet", "def greet(*, name):\n    return f'hello {name}'\n")
        output = _execute_generated(
            _build_invoke_code(
                remote_def=remote,
                args=(),
                kwargs={"name": "Ada"},
                argument_size_max=256_000,
                result_size_max=256_000,
            )
        )
        assert _interpret_meta(_find_meta(output), output, result_size_max=256_000) == "hello Ada"

    def test_remote_exception_preserves_traceback(self) -> None:
        remote = _remote_function("fail", "def fail():\n    raise ValueError('expected')\n")
        output = _execute_generated(
            _build_invoke_code(
                remote_def=remote,
                args=(),
                kwargs={},
                argument_size_max=256_000,
                result_size_max=256_000,
            )
        )
        with pytest.raises(RemoteExecutionFailed, match="expected") as exc_info:
            _interpret_meta(_find_meta(output), output, result_size_max=256_000)
        assert "ValueError" in (exc_info.value.remote_traceback or "")

    def test_remote_result_limit_is_explicit(self) -> None:
        remote = _remote_function("large", "def large():\n    return 'x' * 1_000\n")
        output = _execute_generated(
            _build_invoke_code(
                remote_def=remote,
                args=(),
                kwargs={},
                argument_size_max=256_000,
                result_size_max=100,
            )
        )
        with pytest.raises(RemoteResultTooLarge) as exc_info:
            _interpret_meta(_find_meta(output), output, result_size_max=100)
        assert exc_info.value.result_bytes > exc_info.value.result_size_max

    @pytest.mark.parametrize(
        ("args", "kwargs", "payload_name"),
        [
            (("x" * 1_000,), {}, "positional arguments"),
            ((), {"value": "x" * 1_000}, "keyword arguments"),
        ],
    )
    def test_argument_limit_fails_before_remote_code(
        self,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        payload_name: str,
    ) -> None:
        remote = _remote_function("value", "def value(*args, **kwargs):\n    return None\n")
        with pytest.raises(RemoteArgumentsTooLarge, match=payload_name):
            _build_invoke_code(
                remote_def=remote,
                args=args,
                kwargs=kwargs,
                argument_size_max=100,
                result_size_max=256_000,
            )


class TestResultProtocolValidation:
    """Malformed and oversized responses must fail with bounded errors."""

    def test_finds_last_marker(self) -> None:
        first = _CHOPPA_META_MARKER + json.dumps({"ok": False, "error": "old"})
        last = _CHOPPA_META_MARKER + json.dumps({"ok": True, "data": "new"})
        assert _find_meta(f"{first}\nnoise\n{last}")["data"] == "new"

    @pytest.mark.parametrize(
        "output",
        [
            "no marker",
            _CHOPPA_META_MARKER + "not json",
            _CHOPPA_META_MARKER + "[]",
        ],
    )
    def test_rejects_invalid_metadata(self, output: str) -> None:
        with pytest.raises(RemoteProtocolError):
            _find_meta(output)

    def test_rejects_non_boolean_status(self) -> None:
        with pytest.raises(RemoteProtocolError, match="boolean"):
            _interpret_meta({"ok": "yes", "data": ""}, "", result_size_max=100)

    def test_rejects_invalid_base64(self) -> None:
        with pytest.raises(RemoteProtocolError, match="base64"):
            _interpret_meta({"ok": True, "data": "%%%"}, "", result_size_max=100)

    def test_rejects_invalid_compression(self) -> None:
        data = base64.b64encode(b"not zlib").decode("ascii")
        with pytest.raises(RemoteProtocolError, match="compressed"):
            _interpret_meta({"ok": True, "data": data}, "", result_size_max=100)

    def test_bounded_decompression_rejects_expansion(self) -> None:
        compressed = zlib.compress(b"x" * 10_000)
        data = base64.b64encode(compressed).decode("ascii")
        with pytest.raises(RemoteResultTooLarge):
            _interpret_meta({"ok": True, "data": data}, "", result_size_max=100)

    def test_valid_pickled_value(self) -> None:
        raw = cloudpickle.dumps({"value": 7})
        data = base64.b64encode(zlib.compress(raw)).decode("ascii")
        assert _interpret_meta({"ok": True, "data": data}, "", result_size_max=1_000) == {"value": 7}
