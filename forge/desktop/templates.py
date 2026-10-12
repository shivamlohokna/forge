"""Built-in starter workflow templates for Forge Desktop.

Shell tasks that require a native shell interpreter are generated at import
time based on the current platform so that the correct command is embedded
when a user opens a template.  The task content can always be edited in the
workflow editor before running.
"""

from __future__ import annotations

import copy
import sys
from typing import Any


def _shell_cmd(windows: str, posix: str) -> str:
    """Return the platform-appropriate shell command string."""
    return windows if sys.platform == "win32" else posix


# ─────────────────────────────────────────────────────────────────────────────
# System Health Audit — shell commands differ per platform
# ─────────────────────────────────────────────────────────────────────────────
_HEALTH_DISK_CMD = _shell_cmd(
    windows='powershell -NoProfile -Command "Get-PSDrive -PSProvider FileSystem | Select-Object Name, Free, Used"',
    posix="df -h",
)
_HEALTH_ENV_CMD = _shell_cmd(
    windows='powershell -NoProfile -Command "Write-Output (\'Forge Host: \' + $env:COMPUTERNAME + \' User: \' + $env:USERNAME)"',
    posix='echo "Forge Host: $(hostname)  User: $(whoami)"',
)

# Data Processing Pipeline — shell transform step
_PIPELINE_TRANSFORM_CMD = _shell_cmd(
    windows='powershell -NoProfile -Command "$c = Get-Content raw_input.csv; Write-Output (\'Processed \' + $c.Count + \' lines.\')"',
    posix='awk \'END{print "Processed " NR " lines."}\' raw_input.csv',
)

STARTER_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "system_health_audit",
        "title": "System Health & Disk Audit",
        "description": "Inspect disk usage and environment configuration with dependent shell tasks.",
        "icon": "desktop",
        "tags": ["Shell", "Monitoring", "DAG"],
        # Note displayed in the Home view template card
        "platform_note": "Shell commands are pre-filled for the current OS.",
        "workflow": {
            "name": "System Health Audit",
            "description": "Cross-task system inspection verifying file system and user context.",
            "max_workers": 2,
            "tasks": [
                {
                    "id": "check_disk_space",
                    "name": "check_disk_space",
                    "type": "shell",
                    "timeout": 30.0,
                    "failure_strategy": "STOP",
                    "params": {
                        "command": _HEALTH_DISK_CMD,
                    },
                },
                {
                    "id": "check_environment",
                    "name": "check_environment",
                    "type": "shell",
                    "depends_on": ["check_disk_space"],
                    "timeout": 15.0,
                    "failure_strategy": "STOP",
                    "params": {
                        "command": _HEALTH_ENV_CMD,
                    },
                },
            ],
        },
    },
    {
        "id": "file_backup_pipeline",
        "title": "File Backup & Archiving",
        "description": "Perform atomic file operations, create timestamped notes, and read back content.",
        "icon": "folder",
        "tags": ["File", "Atomic", "Storage"],
        "workflow": {
            "name": "File Backup Pipeline",
            "description": "Demonstrates file creation, validation, and content retrieval.",
            "max_workers": 2,
            "tasks": [
                {
                    "id": "create_backup_manifest",
                    "name": "create_backup_manifest",
                    "type": "file",
                    "failure_strategy": "STOP",
                    "params": {
                        "operation": "write",
                        "path": "backup_manifest.txt",
                        "content": "Forge Automated Backup Manifest\nVersion: 1.0\nStatus: Verified",
                    },
                },
                {
                    "id": "verify_manifest",
                    "name": "verify_manifest",
                    "type": "file",
                    "depends_on": ["create_backup_manifest"],
                    "failure_strategy": "STOP",
                    "params": {
                        "operation": "read",
                        "path": "backup_manifest.txt",
                    },
                },
            ],
        },
    },
    {
        "id": "api_health_monitor",
        "title": "REST API Health Monitor",
        "description": "Query an external or local HTTP service, validate status codes, and record results.",
        "icon": "globe",
        "tags": ["HTTP", "REST", "Network"],
        "workflow": {
            "name": "API Health Monitor",
            "description": "Validates endpoint health and processes HTTP status codes.",
            "max_workers": 2,
            "tasks": [
                {
                    "id": "ping_endpoint",
                    "name": "ping_endpoint",
                    "type": "http",
                    "timeout": 15.0,
                    "failure_strategy": "STOP",
                    "params": {
                        "url": "https://httpbin.org/get",
                        "method": "GET",
                        "expected_status": 200,
                    },
                },
                {
                    "id": "record_health_log",
                    "name": "record_health_log",
                    "type": "file",
                    "depends_on": ["ping_endpoint"],
                    "failure_strategy": "STOP",
                    "params": {
                        "operation": "write",
                        "path": "api_health.log",
                        "content": "HTTP Endpoint check succeeded at expected status 200.",
                    },
                },
            ],
        },
    },
    {
        "id": "data_processing_pipeline",
        "title": "Multi-Stage Processing Pipeline",
        "description": "Complete DAG pipeline combining file preparation, shell compute, and completion steps.",
        "icon": "cpu",
        "tags": ["Multi-Task", "Pipeline", "Parallel"],
        "workflow": {
            "name": "Data Processing Pipeline",
            "description": "Extract, compute, and report stages wired with topological dependencies.",
            "max_workers": 3,
            "tasks": [
                {
                    "id": "stage_input_data",
                    "name": "stage_input_data",
                    "type": "file",
                    "failure_strategy": "STOP",
                    "params": {
                        "operation": "write",
                        "path": "raw_input.csv",
                        "content": "id,event,score\n1,alpha,98\n2,beta,85\n3,gamma,92",
                    },
                },
                {
                    "id": "execute_transformation",
                    "name": "execute_transformation",
                    "type": "shell",
                    "depends_on": ["stage_input_data"],
                    "timeout": 20.0,
                    "failure_strategy": "STOP",
                    "params": {
                        "command": _PIPELINE_TRANSFORM_CMD,
                    },
                },
                {
                    "id": "finalize_report",
                    "name": "finalize_report",
                    "type": "file",
                    "depends_on": ["execute_transformation"],
                    "failure_strategy": "STOP",
                    "params": {
                        "operation": "write",
                        "path": "pipeline_summary.json",
                        "content": '{"status": "COMPLETED", "pipeline": "Data Processing Pipeline"}',
                    },
                },
            ],
        },
    },
]


def get_starter_templates() -> list[dict[str, Any]]:
    """Return a deep copy of all starter workflow templates."""
    return copy.deepcopy(STARTER_TEMPLATES)


def get_template_by_id(template_id: str) -> dict[str, Any] | None:
    """Return a template by its ID, or None if not found."""
    for t in STARTER_TEMPLATES:
        if t["id"] == template_id:
            return copy.deepcopy(t)
    return None

