# Forge Plugin Authoring Guide

Forge features an extensible, decentralized plugin architecture. Any standard Python package can contribute new task types that seamlessly integrate into both the programmatic Python API and declarative workflows (JSON / TOML / YAML).

---

## The `ForgePlugin` Protocol

Plugins implement the runtime-checkable `ForgePlugin` protocol:

```python
from forge.registry.task_registry import TaskRegistry

class MyCustomPlugin:
    """Example Forge Task Plugin."""

    # Unique non-empty name identifying the plugin
    name: str = "my-plugin"

    # Optional metadata
    version: str = "1.0.0"
    min_forge_version: str = "0.2.0"

    def register(self, registry: TaskRegistry) -> None:
        """Register custom task types into the provided TaskRegistry."""
        registry.register("my_plugin:custom_task", MyCustomTask)

    def on_load(self) -> None:
        """Optional lifecycle hook called immediately after registration."""
        pass

    def on_unload(self) -> None:
        """Optional lifecycle hook called during teardown."""
        pass
```

---

## Step-by-Step: Creating a Custom Plugin

### 1. Define Custom Task Class

Subclass `forge.core.task.Task` and implement the `execute` method:

```python
# my_plugin/tasks.py
from forge import ExecutionContext, Task

class SendSlackMessageTask(Task):
    def __init__(
        self,
        name: str,
        channel: str,
        message: str,
        webhook_url: str | None = None,
        **kwargs,
    ):
        super().__init__(name=name, **kwargs)
        self.channel = channel
        self.message = message
        self.webhook_url = webhook_url

    def execute(self, context: ExecutionContext) -> dict:
        print(f"[SlackPlugin] Posting '{self.message}' to #{self.channel}...")
        # Custom HTTP / API logic
        return {"status": "ok", "channel": self.channel}
```

---

### 2. Define the Plugin Class

```python
# my_plugin/plugin.py
from forge.registry.task_registry import TaskRegistry
from .tasks import SendSlackMessageTask

class SlackPlugin:
    name = "slack"
    version = "1.0.0"
    min_forge_version = "0.2.0"

    def register(self, registry: TaskRegistry) -> None:
        registry.register("slack:notify", SendSlackMessageTask)
```

---

### 3. Expose the Entry Point in `pyproject.toml`

Register your plugin under the `forge.plugins` entry point group:

```toml
[project]
name = "forge-slack"
version = "1.0.0"
dependencies = [
    "forge>=0.2.0",
]

[project.entry-points."forge.plugins"]
slack = "my_plugin.plugin:SlackPlugin"
```

---

## Automatic Discovery

When `forge-slack` is installed into any Python environment containing Forge:

1. **CLI Discovery**: Commands like `forge run` and `forge validate` automatically discover all installed `forge.plugins` entry points without requiring code modifications.
2. **Declarative Workflows**: The registered task type becomes immediately available in JSON, TOML, and YAML definitions:

```json
{
  "name": "DeploymentNotification",
  "tasks": [
    {
      "id": "slack_alert",
      "type": "slack:notify",
      "params": {
        "channel": "deployments",
        "message": "Deployment succeeded!"
      }
    }
  ]
}
```

---

## Reference Implementation: `forge-github`

The repository contains an end-to-end reference plugin package in [`forge-github/`](../forge-github/):
- `forge-github/forge_github/tasks.py`: Implements `GitHubCreateIssueTask`.
- `forge-github/forge_github/plugin.py`: Exposes `GitHubPlugin` with `github.create_issue` registration.
- `forge-github/pyproject.toml`: Configures the `forge.plugins` entry point.

---

## Testing Your Plugin

You can test plugin registration and execution using Forge's isolated test patterns:

```python
from forge.plugins.discovery import load_plugin
from forge.registry.task_registry import TaskRegistry
from my_plugin.plugin import SlackPlugin

def test_slack_plugin_registers_types():
    registry = TaskRegistry()
    plugin = SlackPlugin()
    plugin.register(registry)

    assert "slack:notify" in registry
```
