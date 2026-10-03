"""Forge custom exceptions."""


class ForgeError(Exception):
    """Base exception for all Forge errors."""
    pass


class TaskError(ForgeError):
    """Base exception for task-related errors."""
    pass


class TaskExecutionError(TaskError):
    """Raised when a task fails during execution."""
    pass


class TaskTimeoutError(TaskError):
    """Raised when a task exceeds its configured execution timeout."""
    pass


class DependencyError(ForgeError):
    """Base exception for workflow dependency errors."""
    pass


class CircularDependencyError(DependencyError):
    """Raised when a circular dependency (cycle) is detected in a workflow graph."""
    pass


class MissingDependencyError(DependencyError):
    """Raised when a task depends on another task that is not part of the workflow."""
    pass


class LoadError(ForgeError):
    """Raised when loading a workflow file fails."""
    pass


class WorkflowSpecError(LoadError):
    """Raised when a declarative workflow specification is invalid or malformed."""
    pass


class ParameterError(WorkflowSpecError):
    """Raised when workflow parameter declaration, validation, or substitution fails."""
    pass


class OutputError(WorkflowSpecError):
    """Raised when workflow output resolution, reference, or validation fails."""
    pass





class RegistryError(ForgeError):
    """Raised for task-registry registration or lookup failures."""
    pass


class DuplicateTaskTypeError(RegistryError):
    """Raised when registering a task type that is already present."""
    pass


class UnknownTaskTypeError(RegistryError):
    """Raised when resolving or unregistering a task type that is not registered."""
    pass


class PluginError(ForgeError):
    """Base exception for all plugin system errors."""
    pass


class PluginDiscoveryError(PluginError):
    """Raised when entry point discovery fails."""
    pass


class PluginLoadError(PluginError):
    """Raised when loading or importing a plugin entry point fails."""
    pass


class MalformedPluginError(PluginError):
    """Raised when a loaded object fails the ForgePlugin contract validation."""
    pass


class PluginIncompatibleError(PluginError):
    """Raised when a plugin requires an incompatible version of Forge."""
    pass


class PluginLifecycleError(PluginError):
    """Raised when a plugin lifecycle hook (on_load / on_unload) fails."""
    pass



