# Forge Real-World Recipe Catalog

This directory contains executable, production-grade reference workflow recipes demonstrating the capabilities, APIs, and formats supported by Forge.

---

## Catalog Overview

| Recipe | Category | Format | Classification | Description |
|---|---|---|---|---|
| `quickstart` | Getting Started | JSON / Python | **Standalone** | Canonical 3-step pipeline (prepare, verify, report) |
| `build_test` | Developer Automation | JSON | **Standalone** | Project build, configuration write, and test suite execution |
| `file_pipeline` | File Automation | JSON | **Standalone** | Multi-stage file creation, transformation, copy, and archive |
| `backup` | Data & Backup | JSON | **Standalone** | Database dump snapshot, backup copy, and integrity verification |
| `api_pipeline` | API Integration | JSON | **Standalone / External** | REST API HTTP request client with status check and storage |
| `ml_pipeline` | Machine Learning | JSON | **Standalone** | ML dataset preparation, feature generation, and metric validation |
| `github_plugin` | Plugin Extensions | JSON | **Optional Dep / Credentials** | GitHub Issue creation via the `forge-github` extension plugin |

---

## 1. `quickstart` (Getting Started)

### PROBLEM
You need to verify that Forge is installed correctly, understand how tasks pass dependencies, and test a minimal end-to-end pipeline before building complex automation.

### WHAT FORGE DOES
1. `prepare_data` (`file`): Writes a seed JSON file to `data/input.json`.
2. `verify_data` (`file`, depends on `prepare_data`): Reads `data/input.json` to confirm existence.
3. `save_report` (`file`, depends on `verify_data`): Writes a summary completion report to `data/report.json`.

### WHAT YOU NEED
- Python 3.11+
- Forge installed (`pip install -e .`)

### RUN IT
```bash
forge run examples/quickstart.json
# Or Python API format:
python examples/quickstart.py
```

### WHAT YOU WILL SEE
```text
  Execution Summary
  =================
  Workflow:    QuickstartPipeline
  Status:      SUCCESS
  Duration:    0.02s
  Tasks:       3 succeeded, 0 failed, 0 retried, 0 total
```

### HOW TO CUSTOMIZE IT
- Change `"path": "data/input.json"` to your actual target input file path.
- Add downstream tasks depending on `save_report` to process data further.

### WHAT CAN GO WRONG
- Permission error if target directory `data/` is not writable.

---

## 2. `build_test` (Developer Automation)

### PROBLEM
Automate software release steps: write build configuration, execute automated tests, and produce a release artifact sequentially.

### WHAT FORGE DOES
1. `write_config` (`file`): Writes release metadata to `build/config.json`.
2. `run_tests` (`shell`, depends on `write_config`): Runs Python test verification script against `build/config.json`.
3. `generate_artifact` (`file`, depends on `run_tests`): Writes release artifact confirmation to `build/artifact.txt`.

### WHAT YOU NEED
- Python 3.11+
- Standard shell / terminal execution environment

### RUN IT
```bash
forge run examples/declarative/build_test.json
```

### WHAT YOU WILL SEE
`build/artifact.txt` generated cleanly upon test pass.

### HOW TO CUSTOMIZE IT
- Replace `command` in `run_tests` with your test command (e.g. `pytest`, `npm test`, `cargo test`).

### WHAT CAN GO WRONG
- If `run_tests` fails (exit code non-zero), `generate_artifact` will be skipped safely according to DAG rules.

---

## 3. `file_pipeline` (File Automation)

### PROBLEM
Automate file processing pipelines: raw dataset generation, log parsing, file renaming, and multi-directory distribution.

### WHAT FORGE DOES
1. `create_raw_file` (`file`): Writes initial raw dataset to `storage/raw.txt`.
2. `transform_data` (`file`, depends on `create_raw_file`): Writes processed content to `storage/processed.txt`.
3. `archive_data` (`file`, depends on `transform_data`): Copies processed dataset into `storage/archive/processed_v1.txt`.

### WHAT YOU NEED
- Standard filesystem access

### RUN IT
```bash
forge run examples/declarative/file_pipeline.json
```

### WHAT YOU WILL SEE
Raw, processed, and archived dataset files generated in `storage/`.

### HOW TO CUSTOMIZE IT
- Use `operation: "copy"` or `operation: "move"` to shift processed outputs into remote mounts or local targets.

---

## 4. `backup` (Data & Backup Pipeline)

### PROBLEM
Regularly create snapshots of database dumps or state files, create a backup copy in a secondary directory, and verify backup integrity.

### WHAT FORGE DOES
1. `prepare_source` (`file`): Creates snapshot dump at `storage/db_dump.json`.
2. `create_backup` (`file`, depends on `prepare_source`): Copies snapshot to `storage/backups/db_dump_backup.json`.
3. `verify_backup` (`file`, depends on `create_backup`): Reads backup copy to verify data integrity.

### WHAT YOU NEED
- Local or mounted backup directory

### RUN IT
```bash
forge run examples/declarative/backup_workflow.json
```

### WHAT YOU WILL SEE
Backup copy created and validated in `storage/backups/`.

---

## 5. `api_pipeline` (API Integration)

### PROBLEM
Fetch data from external HTTP REST APIs with automatic retries and store the JSON payload locally.

### WHAT FORGE DOES
1. `fetch_http_data` (`http`): Sends HTTP GET request to API endpoint with linear retry policy (2 attempts, 1s delay).
2. `save_api_response` (`file`, depends on `fetch_http_data`): Writes API JSON response to `data/api_response.json`.

### WHAT YOU NEED
- Active internet connection (or local HTTP service)

### RUN IT
```bash
forge run examples/declarative/api_pipeline.json
```

### WHAT CAN GO WRONG
- Fails gracefully with retry telemetry if internet connection is offline or API returns non-200 HTTP status.

---

## 6. `ml_pipeline` (Machine Learning Pipeline)

### PROBLEM
Orchestrate multi-step ML pipelines: prepare training datasets, generate features, validate model metrics, and publish model metadata.

### WHAT FORGE DOES
1. `prepare_dataset` (`file`): Generates synthetic ML training dataset in `ml/dataset.csv`.
2. `generate_features` (`shell`, depends on `prepare_dataset`): Processes CSV dataset to extract features.
3. `validate_metrics` (`file`, depends on `generate_features`): Writes model evaluation metrics to `ml/metrics.json`.

### RUN IT
```bash
forge run examples/declarative/ml_pipeline.json
```

---

## 7. `github_plugin` (Extension Plugins)

### PROBLEM
Trigger GitHub issue creation automatically as part of a release or incident workflow using the `forge-github` plugin.

### WHAT YOU NEED
- `forge-github` package installed (`pip install -e ./forge-github`)
- `GITHUB_TOKEN` environment variable set

### RUN IT
```bash
forge run examples/declarative/github_plugin_workflow.json
```
