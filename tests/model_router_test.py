from importlib import util
from pathlib import Path
import asyncio
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_router_module():
    packages_module = types.ModuleType("packages")
    packages_module.__path__ = [str(ROOT / "packages")]
    models_module = types.ModuleType("packages.models")
    models_module.__path__ = [str(ROOT / "packages" / "models")]
    models_module.select_model = lambda model_provider=None, model_name=None: None
    config_module = types.ModuleType("packages.config")
    config_module.model_provider = "deepseek"
    config_module.model_name = "deepseek-chat"
    config_module.model_names = {"deepseek": {"default": "deepseek-chat"}}
    config_module.custom_models = []
    logging_config_module = types.ModuleType("packages.utils.logging_config")

    class _Logger:
        def info(self, *args, **kwargs):
            pass

        def debug(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    logging_config_module.logger = _Logger()
    chat_model_module = types.ModuleType("packages.models.chat_model")

    class _OpenAIBase:
        def __init__(self, *args, **kwargs):
            pass

    chat_model_module.OpenAIBase = _OpenAIBase

    sys.modules.setdefault("packages", packages_module)
    sys.modules.setdefault("packages.models", models_module)
    sys.modules.setdefault("packages.config", config_module)
    sys.modules.setdefault("packages.utils.logging_config", logging_config_module)
    sys.modules.setdefault("packages.models.chat_model", chat_model_module)

    router_types_spec = util.spec_from_file_location(
        "packages.models.router_types",
        ROOT / "packages" / "models" / "router_types.py",
    )
    router_types_module = util.module_from_spec(router_types_spec)
    sys.modules["packages.models.router_types"] = router_types_module
    router_types_spec.loader.exec_module(router_types_module)

    router_spec = util.spec_from_file_location(
        "packages.models.router",
        ROOT / "packages" / "models" / "router.py",
    )
    router_module = util.module_from_spec(router_spec)
    sys.modules["packages.models.router"] = router_module
    router_spec.loader.exec_module(router_module)
    init_spec = util.spec_from_file_location(
        "packages.models.__init__",
        ROOT / "packages" / "models" / "__init__.py",
    )
    init_module = util.module_from_spec(init_spec)
    init_module.__package__ = "packages.models"
    sys.modules["packages.models.__init__"] = init_module
    init_spec.loader.exec_module(init_module)
    return router_module, init_module, router_types_module.ModelInvocationError


router_module, init_module, ModelInvocationError = _load_router_module()
ModelRouter = router_module.ModelRouter
RoutedPrediction = router_module.RoutedPrediction
RuntimeConfig = router_module.RuntimeConfig
RedisRuntimeStore = router_module.RedisRuntimeStore
ModelRoutingUnavailableError = router_module.ModelRoutingUnavailableError
build_model_router = init_module.build_model_router


class _FailingModel:
    def __init__(self, exc):
        self.exc = exc

    def predict(self, message, stream=False):  # noqa: ARG002
        raise self.exc


class _SuccessfulModel:
    def __init__(self, output):
        self.output = output

    def predict(self, message, stream=False):  # noqa: ARG002
        return self.output


def _config() -> RuntimeConfig:
    return RuntimeConfig(
        model_router_enabled=True,
        circuit_breaker_enabled=True,
        default_route=("deepseek", "deepseek-chat"),
        fallback_chain=[("deepseek", "deepseek-chat"), ("ollama", "qwen3:30b")],
        request_timeout_seconds=45,
        stream_timeout_seconds=90,
        max_retries_per_model=1,
        circuit_breaker_failure_threshold=5,
        circuit_breaker_failure_window_seconds=60,
        circuit_breaker_open_seconds=120,
        circuit_breaker_half_open_probes=2,
        runtime_redis_prefix="threatrag:test:router",
        model_status_ttl_seconds=600,
        request_idempotency_ttl_seconds=300,
        short_cache_ttl_seconds=120,
        rabbitmq_url="amqp://guest:guest@rabbitmq:5672/",
        rabbitmq_task_exchange="threatrag.tasks",
        rabbitmq_task_queue="threatrag.tasks.main",
        rabbitmq_retry_queue="threatrag.tasks.retry",
        rabbitmq_dlq="threatrag.tasks.dlq",
        rabbitmq_max_retries=3,
        rabbitmq_retry_delay_ms=10000,
    )


async def _new_router() -> ModelRouter:
    config = _config()
    store = RedisRuntimeStore(redis_url="redis://localhost:6379/4", config=config)
    await store.clear_prefix()
    return ModelRouter(config=config, runtime_store=store)


def test_router_falls_back_after_retryable_failure():
    async def _run() -> None:
        router = await _new_router()
        try:
            router.register_factory(
                ("deepseek", "deepseek-chat"),
                lambda: _FailingModel(
                    ModelInvocationError(
                        error_type="timeout",
                        retryable=True,
                        counts_for_circuit_breaker=True,
                        message="timed out",
                    )
                ),
            )
            router.register_factory(("ollama", "qwen3:30b"), lambda: _SuccessfulModel("fallback-ok"))

            result = await router.predict(
                "hello",
                preferred_route=("deepseek", "deepseek-chat"),
            )

            assert isinstance(result, RoutedPrediction)
            assert result.output == "fallback-ok"
            assert result.actual_provider == "ollama"
            assert result.actual_model_name == "qwen3:30b"
            assert result.degraded is True
            assert result.route_reason == "retryable_failure_fallback"

            assert await router.runtime_store.get_circuit_state("deepseek", "deepseek-chat") == {
                "state": "open",
                "failures": 5,
            }
            assert await router.runtime_store.get_circuit_state("ollama", "qwen3:30b") == {
                "state": "closed",
                "failures": 0,
            }
        finally:
            await router.runtime_store.clear_prefix()
            await router.runtime_store.close()

    asyncio.run(_run())


def test_router_skips_open_preferred_route_and_uses_fallback():
    async def _run() -> None:
        router = await _new_router()
        try:
            await router.runtime_store.set_circuit_state(
                "deepseek",
                "deepseek-chat",
                "open",
                failures=5,
            )
            router.register_factory(("ollama", "qwen3:30b"), lambda: _SuccessfulModel("from-fallback"))

            result = await router.predict(
                "hello",
                preferred_route=("deepseek", "deepseek-chat"),
            )

            assert result.output == "from-fallback"
            assert result.actual_provider == "ollama"
            assert result.actual_model_name == "qwen3:30b"
            assert result.degraded is True
            assert result.route_reason == "circuit_open_fallback"
        finally:
            await router.runtime_store.clear_prefix()
            await router.runtime_store.close()

    asyncio.run(_run())


def test_router_uses_clear_reason_for_successful_default_route():
    async def _run() -> None:
        router = await _new_router()
        try:
            router.register_factory(
                ("deepseek", "deepseek-chat"),
                lambda: _SuccessfulModel("default-ok"),
            )

            result = await router.predict("hello")

            assert result.output == "default-ok"
            assert result.actual_provider == "deepseek"
            assert result.actual_model_name == "deepseek-chat"
            assert result.degraded is False
            assert result.route_reason == "default_route"
        finally:
            await router.runtime_store.clear_prefix()
            await router.runtime_store.close()

    asyncio.run(_run())


def test_router_raises_meaningful_error_when_all_routes_are_unavailable():
    async def _run() -> None:
        router = await _new_router()
        try:
            await router.runtime_store.set_circuit_state(
                "deepseek",
                "deepseek-chat",
                "open",
                failures=5,
            )
            await router.runtime_store.set_circuit_state(
                "ollama",
                "qwen3:30b",
                "open",
                failures=5,
            )

            try:
                await router.predict("hello", preferred_route=("deepseek", "deepseek-chat"))
            except ModelRoutingUnavailableError as exc:
                assert exc.route_reason == "all_routes_unavailable"
                assert exc.routes == [
                    ("deepseek", "deepseek-chat"),
                    ("ollama", "qwen3:30b"),
                ]
                assert "deepseek:deepseek-chat" in str(exc)
                assert "ollama:qwen3:30b" in str(exc)
            else:
                raise AssertionError("Expected ModelRoutingUnavailableError")
        finally:
            await router.runtime_store.clear_prefix()
            await router.runtime_store.close()

    asyncio.run(_run())


def test_build_model_router_passes_factory_through():
    factory = object()

    router = build_model_router(config=_config(), runtime_store=None, factory=factory)

    try:
        assert router._factory is factory
    finally:
        asyncio.run(router.runtime_store.close())
