"""Structured lifecycle events and pub/sub event dispatcher for Forge V2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class EventType(str, Enum):
    """Lifecycle event types emitted by the Forge execution engine."""

    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    TASK_READY = "TASK_READY"
    TASK_STARTED = "TASK_STARTED"
    TASK_ATTEMPT_STARTED = "TASK_ATTEMPT_STARTED"
    TASK_ATTEMPT_FINISHED = "TASK_ATTEMPT_FINISHED"
    TASK_SUCCEEDED = "TASK_SUCCEEDED"
    TASK_FAILED = "TASK_FAILED"
    TASK_BLOCKED = "TASK_BLOCKED"
    TASK_SKIPPED = "TASK_SKIPPED"
    TASK_CANCELLED = "TASK_CANCELLED"
    WORKFLOW_FINISHED = "WORKFLOW_FINISHED"


@dataclass
class WorkflowEvent:
    """Structured event capturing a point-in-time execution transition."""

    event_type: EventType
    workflow_id: str
    workflow_name: str
    task_id: str | None = None
    task_name: str | None = None
    attempt: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert event to a serializable dictionary."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "attempt": self.attempt,
            "data": self.data,
        }


class EventDispatcher:
    """Pub/Sub dispatcher routing lifecycle events to registered listeners."""

    def __init__(self) -> None:
        self._listeners: dict[EventType | None, list[Callable[[WorkflowEvent], None]]] = {}

    def subscribe(
        self,
        handler: Callable[[WorkflowEvent], None],
        event_type: EventType | None = None,
    ) -> None:
        """Subscribe a callable handler to a specific event type, or all events if None."""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(handler)

    def emit(self, event: WorkflowEvent) -> None:
        """Publish an event to all matching subscribers."""
        # Specific subscribers
        for handler in self._listeners.get(event.event_type, []):
            try:
                handler(event)
            except Exception:
                pass

        # Global subscribers (subscribed to None)
        for handler in self._listeners.get(None, []):
            try:
                handler(event)
            except Exception:
                pass
