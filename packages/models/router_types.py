from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInvocationError(Exception):
    error_type: str
    retryable: bool
    counts_for_circuit_breaker: bool
    message: str = ""

    def __str__(self):
        return self.message or self.error_type
