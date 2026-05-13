from importlib import util
from pathlib import Path
import asyncio
import json
import sys
import types


ROOT = Path(__file__).resolve().parents[1]


def _load_chat_api_module():
    packages_module = types.ModuleType("packages")
    packages_module.__path__ = [str(ROOT / "packages")]
    packages_module.executor = object()
    packages_module.retriever = lambda *args, **kwargs: ("unused", {})

    config_module = types.ModuleType("packages.config")
    config_module.model_provider = "deepseek"
    config_module.model_name = "deepseek-chat"
    config_module.model_names = {"deepseek": {"default": "deepseek-chat"}}
    config_module.custom_models = []

    models_module = types.ModuleType("packages.models")
    models_module.__path__ = [str(ROOT / "packages" / "models")]

    def _unexpected_select_model(*args, **kwargs):
        raise AssertionError("chat_api should route predictions via the model router")

    models_module.select_model = _unexpected_select_model
    models_module.build_model_router = lambda config=None, runtime_store=None, factory=None: None

    class _HistoryManager:
        def __init__(self, history, system_prompt=None):
            self.history = history
            self.system_prompt = system_prompt
            self.messages = []

        def get_history_with_msg(self, query, max_rounds=None):  # noqa: ARG002
            messages = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": query})
            return messages

        def add_user(self, query):  # noqa: ARG002
            return None

        def update_ai(self, content):
            return [{"role": "assistant", "content": content}]

    core_module = types.ModuleType("packages.core")
    core_module.HistoryManager = _HistoryManager

    logging_module = types.ModuleType("packages.utils.logging_config")

    class _Logger:
        def debug(self, *args, **kwargs):
            pass

        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    logging_module.logger = _Logger()

    redis_session_module = types.ModuleType("rag.cache.redis_session")

    class _RedisSessionManager:
        def __init__(self, *args, **kwargs):
            pass

    redis_session_module.RedisSessionManager = _RedisSessionManager

    chat_session_module = types.ModuleType("packages.manager.chat_session_manager")

    class _ChatSessionManager:
        async def create_session(self, **kwargs):
            return "thread-1"

        async def get_session(self, **kwargs):
            return {"id": "thread-1"}

        async def get_history(self, **kwargs):
            return []

        async def add_message(self, **kwargs):
            return None

    chat_session_module.get_chat_session_manager = lambda redis_manager=None: _ChatSessionManager()

    coroutine_pool_module = types.ModuleType("rag.utils.coroutine_pool")

    class _CoroutinePool:
        def __init__(self, *args, **kwargs):
            pass

        async def submit(self, task):
            return await task

    coroutine_pool_module.CoroutinePool = _CoroutinePool

    dotenv_module = types.ModuleType("dotenv")
    dotenv_module.load_dotenv = lambda: None

    rag_module = types.ModuleType("rag")
    rag_module.__path__ = [str(ROOT / "rag")]

    rag_cache_module = types.ModuleType("rag.cache")
    rag_cache_module.__path__ = [str(ROOT / "rag" / "cache")]

    rag_config_module = types.ModuleType("rag.config")
    rag_config_module.__path__ = [str(ROOT / "rag" / "config")]

    rag_utils_module = types.ModuleType("rag.utils")
    rag_utils_module.__path__ = [str(ROOT / "rag" / "utils")]

    redis_runtime_module = types.ModuleType("rag.cache.redis_runtime")

    class _RedisRuntimeStore:
        def __init__(self, *args, **kwargs):
            pass

    redis_runtime_module.RedisRuntimeStore = _RedisRuntimeStore

    runtime_config_module = types.ModuleType("rag.config.runtime_config")

    class _RuntimeConfig:
        @classmethod
        def from_env(cls):
            return cls()

    runtime_config_module.RuntimeConfig = _RuntimeConfig

    fastapi_module = types.ModuleType("fastapi")

    class _APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            def _decorator(func):
                return func
            return _decorator

        def post(self, *args, **kwargs):
            def _decorator(func):
                return func
            return _decorator

        def put(self, *args, **kwargs):
            def _decorator(func):
                return func
            return _decorator

        def delete(self, *args, **kwargs):
            def _decorator(func):
                return func
            return _decorator

    class _HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    def _identity(value=None, **kwargs):  # noqa: ARG001
        return value

    fastapi_module.APIRouter = _APIRouter
    fastapi_module.Body = _identity
    fastapi_module.Depends = _identity
    fastapi_module.HTTPException = _HTTPException
    fastapi_module.Header = _identity
    fastapi_module.Request = _identity

    fastapi_responses_module = types.ModuleType("fastapi.responses")

    class _StreamingResponse:
        def __init__(self, body_iterator, media_type=None):  # noqa: ARG002
            self.body_iterator = body_iterator

    fastapi_responses_module.StreamingResponse = _StreamingResponse

    langchain_messages_module = types.ModuleType("langchain_core.messages")

    class _AIMessageChunk:
        def __init__(self, content=None, reasoning_content=None, is_full=False):
            self.content = content
            self.reasoning_content = reasoning_content
            self.is_full = is_full

    langchain_messages_module.AIMessageChunk = _AIMessageChunk

    slowapi_module = types.ModuleType("slowapi")
    class _Limiter:
        def __init__(self, *args, **kwargs): pass
        def limit(self, *args, **kwargs):
            def _decorator(func): return func
            return _decorator
    slowapi_module.Limiter = _Limiter

    slowapi_util_module = types.ModuleType("slowapi.util")
    slowapi_util_module.get_remote_address = lambda *args, **kwargs: "127.0.0.1"

    sys.modules["slowapi"] = slowapi_module
    sys.modules["slowapi.util"] = slowapi_util_module
    sys.modules["packages"] = packages_module
    sys.modules["packages.config"] = config_module
    sys.modules["packages.models"] = models_module
    sys.modules["packages.core"] = core_module
    sys.modules["packages.utils.logging_config"] = logging_module
    sys.modules["rag"] = rag_module
    sys.modules["rag.cache"] = rag_cache_module
    sys.modules["rag.config"] = rag_config_module
    sys.modules["rag.utils"] = rag_utils_module
    sys.modules["rag.cache.redis_session"] = redis_session_module
    sys.modules["rag.cache.redis_runtime"] = redis_runtime_module
    sys.modules["rag.config.runtime_config"] = runtime_config_module
    sys.modules["packages.manager.chat_session_manager"] = chat_session_module
    sys.modules["rag.utils.coroutine_pool"] = coroutine_pool_module
    sys.modules["dotenv"] = dotenv_module
    sys.modules["fastapi"] = fastapi_module
    sys.modules["fastapi.responses"] = fastapi_responses_module
    sys.modules["langchain_core.messages"] = langchain_messages_module

    spec = util.spec_from_file_location(
        "rag.api.routers.chat_api_task5_test_module",
        ROOT / "rag" / "api" / "routers" / "chat_api.py",
    )
    module = util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_temporary_chat_stream_contains_actual_model_metadata_from_router():
    chat_api = _load_chat_api_module()

    class _Delta:
        def __init__(self, content):
            self.content = content

    class _RouterResult:
        def __init__(self, output):
            self.output = output
            self.actual_provider = "ollama"
            self.actual_model_name = "qwen3:30b"
            self.degraded = True
            self.route_reason = "retryable_failure_fallback"

    class _Router:
        async def predict(self, message, preferred_route=None, stream=False):
            assert stream is True
            assert preferred_route == ("deepseek", "deepseek-chat")
            assert message[-1]["content"] == "hello router"
            return _RouterResult(iter([_Delta("hello "), _Delta("world")]))

    chat_api.model_router = _Router()

    async def _run():
        response = await chat_api.temporary_chat(
            request="mock_request",
            query="hello router",
            meta={"model_provider": "deepseek", "model_name": "deepseek-chat"},
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(json.loads(chunk.decode("utf-8")))
        return chunks

    chunks = asyncio.run(_run())

    assert [chunk["response"] for chunk in chunks[:2]] == ["hello ", "world"]
    assert chunks[-1]["status"] == "finished"
    assert chunks[-1]["meta"]["expected_model_provider"] == "deepseek"
    assert chunks[-1]["meta"]["expected_model_name"] == "deepseek-chat"
    assert chunks[-1]["meta"]["actual_model_provider"] == "ollama"
    assert chunks[-1]["meta"]["actual_model_name"] == "qwen3:30b"
    assert chunks[-1]["meta"]["degraded"] is True
    assert chunks[-1]["meta"]["route_reason"] == "retryable_failure_fallback"


def test_call_returns_actual_model_metadata_from_router():
    chat_api = _load_chat_api_module()

    class _Response:
        def __init__(self, content):
            self.content = content

    class _RouterResult:
        def __init__(self, output):
            self.output = output
            self.actual_provider = "ollama"
            self.actual_model_name = "qwen3:30b"
            self.degraded = True
            self.route_reason = "retryable_failure_fallback"

    class _Router:
        async def predict(self, message, preferred_route=None, stream=False):
            assert stream is False
            assert preferred_route == ("deepseek", "deepseek-chat")
            assert message == "hello router"
            return _RouterResult(_Response("call ok"))

    chat_api.model_router = _Router()

    async def _run():
        return await chat_api.call(
            query="hello router",
            meta={"model_provider": "deepseek", "model_name": "deepseek-chat"},
        )

    payload = asyncio.run(_run())

    assert payload["response"] == "call ok"
    assert payload["expected_model_provider"] == "deepseek"
    assert payload["expected_model_name"] == "deepseek-chat"
    assert payload["actual_model_provider"] == "ollama"
    assert payload["actual_model_name"] == "qwen3:30b"
    assert payload["degraded"] is True
    assert payload["route_reason"] == "retryable_failure_fallback"


def test_call_uses_default_route_reason_when_model_not_explicitly_requested():
    chat_api = _load_chat_api_module()

    class _Response:
        def __init__(self, content):
            self.content = content

    class _RouterResult:
        def __init__(self, output):
            self.output = output
            self.actual_provider = "deepseek"
            self.actual_model_name = "deepseek-chat"
            self.degraded = False
            self.route_reason = "default_route"

    class _Router:
        async def predict(self, message, preferred_route=None, stream=False):
            assert stream is False
            assert preferred_route is None
            assert message == "hello default"
            return _RouterResult(_Response("default ok"))

    chat_api.model_router = _Router()

    async def _run():
        return await chat_api.call(query="hello default", meta={})

    payload = asyncio.run(_run())

    assert payload["response"] == "default ok"
    assert payload["expected_model_provider"] == "deepseek"
    assert payload["expected_model_name"] == "deepseek-chat"
    assert payload["actual_model_provider"] == "deepseek"
    assert payload["actual_model_name"] == "deepseek-chat"
    assert payload["degraded"] is False
    assert payload["route_reason"] == "default_route"


def test_stream_retrieval_gating_still_respects_use_web_without_db_id():
    chat_api = _load_chat_api_module()
    retriever_calls = []

    def _retriever(query, messages, meta):
        retriever_calls.append((query, messages, dict(meta)))
        return ("hello routed", {})

    chat_api.retriever = _retriever

    class _RouterResult:
        def __init__(self, output):
            self.output = output
            self.actual_provider = "deepseek"
            self.actual_model_name = "deepseek-chat"
            self.degraded = False
            self.route_reason = "default_route"

    class _Delta:
        def __init__(self, content):
            self.content = content

    class _Router:
        async def predict(self, message, preferred_route=None, stream=False):
            assert stream is True
            assert message[-1]["content"] == "hello routed"
            return _RouterResult(iter([_Delta("ok")]))

    chat_api.model_router = _Router()

    async def _run():
        response = await chat_api.chat_post(
            request="mock_request",
            query="hello",
            user_id=1,
            thread_id="thread-1",
            meta={"use_web": True},
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(json.loads(chunk.decode("utf-8")))
        return chunks

    chunks = asyncio.run(_run())

    assert retriever_calls
    assert chunks[0]["status"] == "searching"
    assert chunks[1]["status"] == "generating"
if __name__ == "__main__":
    print("Running Chat API Task 5 tests...")
    import inspect

    functions = [
        obj for name, obj in inspect.getmembers(sys.modules[__name__])
        if (inspect.isfunction(obj) or inspect.iscoroutinefunction(obj)) and name.startswith("test_")
    ]
    
    passed = 0
    failed = 0
    for func in functions:
        print(f"Running {func.__name__}...", end=" ", flush=True)
        try:
            if inspect.iscoroutinefunction(func):
                asyncio.run(func())
            else:
                func()
            print("PASSED")
            passed += 1
        except Exception as e:
            print(f"FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
            
    print(f"\nTests complete: {passed} passed, {failed} failed.")
    if failed > 0:
        sys.exit(1)
