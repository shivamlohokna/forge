"""Forge - Serious Python Workflow Automation and Execution Platform."""

from forge.core import (
    ConsoleLoggingHook,
    Engine,
    EngineHook,
    EventDispatcher,
    EventType,
    ExecutionContext,
    FailureStrategy,
    RetryPolicy,
    SequentialExecutor,
    Task,
    TaskAttempt,
    TaskExecutor,
    TaskResult,
    TaskStatus,
    ThreadPoolTaskExecutor,
    Workflow,
    WorkflowEvent,
    WorkflowResult,
    WorkflowStatus,
)
from forge.logging import (
    ForgeJsonFormatter,
    ForgeTextFormatter,
    setup_logging,
)
from forge.tasks import (
    FileOperation,
    FileTask,
    FunctionTask,
    HTTPMethod,
    HTTPResult,
    HTTPTask,
    ShellResult,
    ShellTask,
)

__version__ = "0.2.0"

__all__ = [
    "Task",
    "TaskStatus",
    "FailureStrategy",
    "RetryPolicy",
    "ExecutionContext",
    "TaskAttempt",
    "TaskResult",
    "WorkflowStatus",
    "WorkflowResult",
    "Workflow",
    "Engine",
    "EngineHook",
    "ConsoleLoggingHook",
    "TaskExecutor",
    "SequentialExecutor",
    "ThreadPoolTaskExecutor",
    "EventType",
    "WorkflowEvent",
    "EventDispatcher",
    "FunctionTask",
    "FileTask",
    "FileOperation",
    "ShellTask",
    "ShellResult",
    "HTTPTask",
    "HTTPResult",
    "HTTPMethod",
    "setup_logging",
    "ForgeTextFormatter",
    "ForgeJsonFormatter",
]

