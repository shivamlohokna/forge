"""Forge V2 persistence layer.

Public surface of the persistence package:

    from forge.persistence import ExecutionStore
    from forge.persistence.models import WorkflowRunRecord, TaskRunRecord, TaskAttemptRecord
    from forge.persistence.schema import SCHEMA_VERSION, init_schema, get_schema_version
"""

from .store import ExecutionStore
from .models import WorkflowRunRecord, TaskRunRecord, TaskAttemptRecord
from .schema import SCHEMA_VERSION, init_schema, get_schema_version

__all__ = [
    # Primary interface
    "ExecutionStore",
    # Row models (for typing in callers)
    "WorkflowRunRecord",
    "TaskRunRecord",
    "TaskAttemptRecord",
    # Schema utilities
    "SCHEMA_VERSION",
    "init_schema",
    "get_schema_version",
]
