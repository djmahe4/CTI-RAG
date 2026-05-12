from importlib import util
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_model_modules():
    packages_module = types.ModuleType("packages")
    packages_module.__path__ = [str(ROOT / "packages")]
    models_module = types.ModuleType("packages.models")
    models_module.__path__ = [str(ROOT / "packages" / "models")]
    utils_module = types.ModuleType("packages.utils")

    class _Logger:
        def debug(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

    utils_module.logger = _Logger()
    utils_module.get_docker_safe_url = lambda value: value

    openai_module = types.ModuleType("openai")

    class _OpenAI:
        def __init__(self, *args, **kwargs):
            pass

    openai_module.OpenAI = _OpenAI

    langchain_openai_module = types.ModuleType("langchain_openai")

    class _ChatOpenAI:
        def __init__(self, *args, **kwargs):
            pass

    langchain_openai_module.ChatOpenAI = _ChatOpenAI

    sys.modules.setdefault("packages", packages_module)
    sys.modules.setdefault("packages.models", models_module)
    sys.modules.setdefault("packages.utils", utils_module)
    sys.modules.setdefault("openai", openai_module)
    sys.modules.setdefault("langchain_openai", langchain_openai_module)

    router_spec = util.spec_from_file_location(
        "packages.models.router_types",
        ROOT / "packages" / "models" / "router_types.py",
    )
    router_module = util.module_from_spec(router_spec)
    sys.modules["packages.models.router_types"] = router_module
    router_spec.loader.exec_module(router_module)

    chat_spec = util.spec_from_file_location(
        "packages.models.chat_model",
        ROOT / "packages" / "models" / "chat_model.py",
    )
    chat_module = util.module_from_spec(chat_spec)
    sys.modules["packages.models.chat_model"] = chat_module
    chat_spec.loader.exec_module(chat_module)

    return chat_module, router_module.ModelInvocationError


chat_model, ModelInvocationError = _load_model_modules()
OpenAIBase = chat_model.OpenAIBase
classify_model_exception = chat_model.classify_model_exception


class _DummyChatCompletions:
    def __init__(self, response_or_exc):
        self._response_or_exc = response_or_exc

    def create(self, **kwargs):
        if isinstance(self._response_or_exc, Exception):
            raise self._response_or_exc
        return self._response_or_exc


class _DummyClient:
    def __init__(self, response_or_exc):
        self.chat = type("Chat", (), {"completions": _DummyChatCompletions(response_or_exc)})()


def _make_model(response_or_exc):
    model = OpenAIBase(api_key="key", base_url="http://example.com", model_name="test-model")
    model.client = _DummyClient(response_or_exc)
    return model


def test_timeout_is_retryable():
    model = _make_model(TimeoutError("timed out"))

    with pytest.raises(ModelInvocationError) as err:
        model._get_response([{"role": "user", "content": "hello"}])

    assert err.value.retryable is True
    assert err.value.counts_for_circuit_breaker is True
    assert err.value.error_type == "timeout"


def test_bad_request_is_not_retryable():
    model = _make_model(ValueError("bad input"))

    with pytest.raises(ModelInvocationError) as err:
        model._get_response([{"role": "user", "content": "hello"}])

    assert err.value.retryable is False
    assert err.value.counts_for_circuit_breaker is False
    assert err.value.error_type == "bad_request"


def test_protocol_error_is_not_retryable():
    model = _make_model(type("Resp", (), {"choices": []})())

    with pytest.raises(ModelInvocationError) as err:
        model._get_response([{"role": "user", "content": "hello"}])

    assert err.value.retryable is False
    assert err.value.counts_for_circuit_breaker is False
    assert err.value.error_type == "protocol_error"


def test_classify_model_exception_falls_back_to_retryable_upstream_error():
    err = classify_model_exception(RuntimeError("upstream exploded"))

    assert err.retryable is True
    assert err.counts_for_circuit_breaker is True
    assert err.error_type == "upstream_error"
