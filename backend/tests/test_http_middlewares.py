"""Tests for config-driven HTTP middleware plugin loading via extensions_config.json."""

from unittest.mock import MagicMock, patch

from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.app import _load_http_middlewares


class _FakeMiddlewareA(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


class _FakeMiddlewareB(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await call_next(request)


def _mock_extensions_config(*, http_middlewares=None):
    """Build a mock ExtensionsConfig with optional httpMiddlewares in model_extra."""
    extra = {}
    if http_middlewares is not None:
        extra["httpMiddlewares"] = http_middlewares
    return MagicMock(model_extra=extra)


def test_valid_middleware_loaded_and_registered():
    """A valid builder path is resolved, invoked, and registered on the app."""

    def fake_builder():
        return _FakeMiddlewareA

    app = MagicMock()
    config = _mock_extensions_config(http_middlewares=["my_package.auth:build_middleware"])

    with (
        patch("app.gateway.app.get_extensions_config", return_value=config),
        patch("app.gateway.app.resolve_variable", return_value=fake_builder),
    ):
        _load_http_middlewares(app)

    app.add_middleware.assert_called_once_with(_FakeMiddlewareA)


def test_multiple_middlewares_registered_in_order():
    """Multiple builder paths are resolved and registered in declaration order."""
    builders = [lambda: _FakeMiddlewareA, lambda: _FakeMiddlewareB]
    call_idx = iter(range(len(builders)))

    def mock_resolve(path):
        return builders[next(call_idx)]

    app = MagicMock()
    config = _mock_extensions_config(http_middlewares=["pkg.a:build_a", "pkg.b:build_b"])

    with (
        patch("app.gateway.app.get_extensions_config", return_value=config),
        patch("app.gateway.app.resolve_variable", side_effect=mock_resolve),
    ):
        _load_http_middlewares(app)

    assert app.add_middleware.call_count == 2
    calls = app.add_middleware.call_args_list
    assert calls[0].args[0] is _FakeMiddlewareA
    assert calls[1].args[0] is _FakeMiddlewareB


def test_builder_returning_none_is_skipped():
    """A builder that returns None is logged and skipped."""

    def builder_none():
        return None

    app = MagicMock()
    config = _mock_extensions_config(http_middlewares=["pkg.mod:build_none"])

    with (
        patch("app.gateway.app.get_extensions_config", return_value=config),
        patch("app.gateway.app.resolve_variable", return_value=builder_none),
    ):
        _load_http_middlewares(app)

    app.add_middleware.assert_not_called()


def test_resolve_error_logged_and_others_continue():
    """An ImportError from resolve_variable is caught; subsequent middlewares still load."""

    def fake_builder():
        return _FakeMiddlewareA

    effects = [ImportError("no module named broken"), fake_builder]

    def mock_resolve(path):
        result = effects.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    app = MagicMock()
    config = _mock_extensions_config(http_middlewares=["broken.mod:build", "good.mod:build"])

    with (
        patch("app.gateway.app.get_extensions_config", return_value=config),
        patch("app.gateway.app.resolve_variable", side_effect=mock_resolve),
    ):
        _load_http_middlewares(app)

    app.add_middleware.assert_called_once_with(_FakeMiddlewareA)


def test_builder_exception_logged_and_others_continue():
    """An exception raised by the builder itself is caught; other middlewares still load."""

    def exploding_builder():
        raise RuntimeError("builder crashed")

    def good_builder():
        return _FakeMiddlewareA

    resolve_results = iter([exploding_builder, good_builder])

    app = MagicMock()
    config = _mock_extensions_config(http_middlewares=["broken:build", "good:build"])

    with (
        patch("app.gateway.app.get_extensions_config", return_value=config),
        patch("app.gateway.app.resolve_variable", side_effect=lambda p: next(resolve_results)),
    ):
        _load_http_middlewares(app)

    app.add_middleware.assert_called_once_with(_FakeMiddlewareA)


def test_missing_http_middlewares_field_is_noop():
    """No httpMiddlewares key in config results in no error and no registration."""
    app = MagicMock()
    config = _mock_extensions_config(http_middlewares=None)

    with patch("app.gateway.app.get_extensions_config", return_value=config):
        _load_http_middlewares(app)

    app.add_middleware.assert_not_called()


def test_single_string_normalized_to_list():
    """A bare string value is treated as a single-element list."""

    def fake_builder():
        return _FakeMiddlewareA

    app = MagicMock()
    config = _mock_extensions_config(http_middlewares="my_package.auth:build_middleware")

    with (
        patch("app.gateway.app.get_extensions_config", return_value=config),
        patch("app.gateway.app.resolve_variable", return_value=fake_builder),
    ):
        _load_http_middlewares(app)

    app.add_middleware.assert_called_once_with(_FakeMiddlewareA)


def test_invalid_type_logged_as_warning():
    """A non-string/non-list value for httpMiddlewares is logged and skipped."""
    app = MagicMock()
    config = _mock_extensions_config(http_middlewares=42)

    with patch("app.gateway.app.get_extensions_config", return_value=config):
        _load_http_middlewares(app)

    app.add_middleware.assert_not_called()


def test_extensions_config_none_is_noop():
    """When get_extensions_config() returns None, nothing happens."""
    app = MagicMock()

    with patch("app.gateway.app.get_extensions_config", return_value=None):
        _load_http_middlewares(app)

    app.add_middleware.assert_not_called()


def test_builder_returning_non_class_is_skipped():
    """A builder that returns an instance (not a class) is skipped."""

    def builder_returns_instance():
        return "not a class"

    app = MagicMock()
    config = _mock_extensions_config(http_middlewares=["pkg:build_bad"])

    with (
        patch("app.gateway.app.get_extensions_config", return_value=config),
        patch("app.gateway.app.resolve_variable", return_value=builder_returns_instance),
    ):
        _load_http_middlewares(app)

    app.add_middleware.assert_not_called()
