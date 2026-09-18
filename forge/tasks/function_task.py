"""Concrete FunctionTask implementation for Forge V2.

This module provides the first concrete Task contract implementation,
allowing arbitrary Python callables (functions, lambdas, methods) to be
executed as managed tasks in a Forge workflow.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from ..core.task import (
    ExecutionContext,
    FailureStrategy,
    RetryPolicy,
    Task,
)


class FunctionTask(Task):
    """A task that delegates its execution logic to a user-provided Python callable.

    The callable can accept:
    - An `ExecutionContext` instance (if declared in its signature), or
    - Custom positional/keyword arguments provided via `fn_args` / `fn_kwargs`, or
    - No arguments at all (pure parameterless function/lambda).
    """

    def __init__(
        self,
        name: str,
        fn: Callable[..., Any],
        fn_args: tuple[Any, ...] | None = None,
        fn_kwargs: dict[str, Any] | None = None,
        task_id: str | None = None,
        max_retries: int = 0,
        retry_delay: float = 0.0,
        retry_policy: RetryPolicy | None = None,
        failure_strategy: FailureStrategy | str = FailureStrategy.STOP,
        timeout: float | None = None,
        description: str = "",
    ) -> None:
        super().__init__(
            name=name,
            task_id=task_id,
            max_retries=max_retries,
            retry_delay=retry_delay,
            retry_policy=retry_policy,
            failure_strategy=failure_strategy,
            timeout=timeout,
            description=description,
        )

        if not callable(fn):
            raise TypeError(
                f"FunctionTask requires a callable for 'fn', got {type(fn).__name__}"
            )

        self.fn: Callable[..., Any] = fn
        self.fn_args: tuple[Any, ...] = fn_args or ()
        self.fn_kwargs: dict[str, Any] = fn_kwargs or {}

    def execute(self, context: ExecutionContext) -> Any:
        """Invoke the wrapped callable, injecting context if appropriate."""
        sig = inspect.signature(self.fn)
        params = list(sig.parameters.values())

        # Case 1: Callable expects no arguments
        if not params and not self.fn_args and not self.fn_kwargs:
            return self.fn()

        # Case 2: Inspect if 'context' is an explicit parameter
        has_context_param = any(
            p.name == "context" or p.annotation is ExecutionContext
            for p in params
        )

        call_args = list(self.fn_args)
        call_kwargs = dict(self.fn_kwargs)

        if has_context_param:
            call_kwargs["context"] = context
        elif len(params) == 1 and not call_args and not call_kwargs:
            # Single parameter function with no explicit args supplied -> pass context
            call_args.append(context)

        return self.fn(*call_args, **call_kwargs)

    def __repr__(self) -> str:
        fn_name = getattr(self.fn, "__name__", str(self.fn))
        return (
            f"<FunctionTask id='{self.task_id}' name='{self.name}' "
            f"fn='{fn_name}' status='{self.status.value}'>"
        )
