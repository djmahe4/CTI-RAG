from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable

from rag.cache.redis_runtime import RedisRuntimeStore
from rag.config.runtime_config import RuntimeConfig

from .router_types import ModelInvocationError


Route = tuple[str, str]
ModelFactory = Callable[[], Any]


def _default_factory(route: Route) -> Any:
    from packages.models import select_model

    provider, model_name = route
    return select_model(model_provider=provider, model_name=model_name)


def _classify_exception(exc: Exception) -> ModelInvocationError:
    if isinstance(exc, ModelInvocationError):
        return exc

    from .chat_model import classify_model_exception

    return classify_model_exception(exc)


@dataclass(frozen=True, slots=True)
class RoutedPrediction:
    output: Any
    actual_provider: str
    actual_model_name: str
    degraded: bool
    route_reason: str


@dataclass(frozen=True, slots=True)
class ModelRoutingUnavailableError(RuntimeError):
    routes: list[Route]
    route_reason: str = "all_routes_unavailable"

    def __str__(self) -> str:
        route_labels = ", ".join(f"{provider}:{model_name}" for provider, model_name in self.routes)
        return f"No available model routes ({self.route_reason}): {route_labels}"


class ModelRouter:
    def __init__(
        self,
        config: RuntimeConfig | None = None,
        runtime_store: RedisRuntimeStore | None = None,
        factory: Callable[[Route], Any] | None = None,
    ) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.runtime_store = runtime_store or RedisRuntimeStore(config=self.config)
        self._factory = factory or _default_factory
        self._registered_factories: dict[Route, ModelFactory] = {}

    def register_factory(self, route: Route, factory: ModelFactory) -> None:
        self._registered_factories[route] = factory

    async def predict(
        self,
        message: Any,
        preferred_route: Route | None = None,
        stream: bool = False,
    ) -> RoutedPrediction:
        routes = self._candidate_routes(preferred_route)
        fallback_reason: str | None = None
        last_error: ModelInvocationError | None = None

        for index, route in enumerate(routes):
            if self.config.circuit_breaker_enabled:
                state = await self.runtime_store.get_circuit_state(*route)
                if state.get("state") == "open":
                    fallback_reason = "circuit_open_fallback"
                    continue

            try:
                output = await self._predict_with_route(route, message, stream=stream)
            except Exception as exc:
                model_error = _classify_exception(exc)
                last_error = model_error

                if self.config.circuit_breaker_enabled and model_error.counts_for_circuit_breaker:
                    await self.runtime_store.set_circuit_state(
                        route[0],
                        route[1],
                        "open",
                        failures=self.config.circuit_breaker_failure_threshold,
                        ttl_seconds=self.config.circuit_breaker_open_seconds,
                    )

                if not model_error.retryable:
                    raise model_error

                if index < len(routes) - 1:
                    fallback_reason = "retryable_failure_fallback"
                    continue

                raise model_error

            if self.config.circuit_breaker_enabled:
                await self.runtime_store.set_circuit_state(route[0], route[1], "closed", failures=0)

            actual_provider, actual_model_name = route
            requested_route = preferred_route or self.config.default_route
            degraded = route != requested_route
            if fallback_reason is not None:
                route_reason = fallback_reason
            elif preferred_route is not None:
                route_reason = "preferred_route"
            else:
                route_reason = "default_route"
            return RoutedPrediction(
                output=output,
                actual_provider=actual_provider,
                actual_model_name=actual_model_name,
                degraded=degraded,
                route_reason=route_reason,
            )

        if last_error is not None:
            raise last_error

        raise ModelRoutingUnavailableError(routes=routes)

    def _candidate_routes(self, preferred_route: Route | None) -> list[Route]:
        requested_route = preferred_route or self.config.default_route
        routes: list[Route] = []
        for route in [requested_route, *self.config.fallback_chain]:
            if route not in routes:
                routes.append(route)
        return routes

    async def _predict_with_route(self, route: Route, message: Any, stream: bool = False) -> Any:
        model = self._build_model(route)
        result = model.predict(message, stream=stream)
        if inspect.isawaitable(result):
            return await result
        return result

    def _build_model(self, route: Route) -> Any:
        factory = self._registered_factories.get(route)
        if factory is not None:
            return factory()
        return self._factory(route)
