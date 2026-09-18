"""Tests for the Forge configuration layer: model, discovery, resolution, CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from forge.cli.commands import run_command
from forge.cli.main import main
from forge.config import ConfigError, ForgeConfig, load_config, resolve_config
from forge.config.loader import _find_config_file
from forge.persistence import ExecutionStore


def _write_workflow(directory: Path, name: str = "wf.py") -> Path:
    path = directory / name
    path.write_text(
        "from forge import FunctionTask, Workflow\n"
        "def work(ctx): return 'ok'\n"
        "def get_workflow():\n"
        "    t = FunctionTask('work', fn=work)\n"
        "    return Workflow('ConfigWF').add_task(t)\n",
        encoding="utf-8",
    )
    return path


def _write_toml(directory: Path, body: str, name: str = "forge.toml") -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("FORGE_")}


# ── ForgeConfig model ────────────────────────────────────────────────────────

class TestForgeConfigModel:
    def test_default_values(self):
        cfg = ForgeConfig()
        assert cfg.database is None
        assert cfg.workers == 1
        assert cfg.log_level == "INFO"

    def test_from_dict_partial(self):
        cfg = ForgeConfig.from_dict({"database": "my.db"})
        assert cfg.database == "my.db"
        assert cfg.workers == 1  # default preserved

    def test_from_dict_all_fields(self):
        cfg = ForgeConfig.from_dict({
            "database": ".forge/prod.db",
            "workers": 8,
            "log_level": "debug",
        })
        assert cfg.database == ".forge/prod.db"
        assert cfg.workers == 8
        assert cfg.log_level == "DEBUG"

    def test_from_dict_unknown_keys_ignored(self):
        cfg = ForgeConfig.from_dict({"database": "x.db", "unknown_future_key": 42})
        assert cfg.database == "x.db"

    def test_from_dict_invalid_workers(self):
        with pytest.raises(ValueError, match="workers must be >= 1"):
            ForgeConfig.from_dict({"workers": 0})

    def test_from_dict_wrong_workers_type(self):
        with pytest.raises(TypeError, match="workers must be an integer"):
            ForgeConfig.from_dict({"workers": "four"})

    def test_from_dict_wrong_database_type(self):
        with pytest.raises(TypeError, match="database must be a string"):
            ForgeConfig.from_dict({"database": 123})

    def test_from_dict_empty(self):
        cfg = ForgeConfig.from_dict({})
        assert cfg == ForgeConfig()

    def test_equality(self):
        a = ForgeConfig(database="a.db", workers=2)
        b = ForgeConfig(database="a.db", workers=2)
        assert a == b

    def test_inequality(self):
        a = ForgeConfig(workers=1)
        b = ForgeConfig(workers=4)
        assert a != b


# ── Config file discovery ────────────────────────────────────────────────────

class TestConfigDiscovery:
    def test_finds_file_in_current_dir(self, tmp_path: Path):
        cfg_file = _write_toml(tmp_path, '[forge]\ndatabase = "out.db"\n')
        found = _find_config_file(tmp_path)
        assert found == cfg_file

    def test_finds_file_from_nested_directory(self, tmp_path: Path):
        cfg_file = _write_toml(tmp_path, "[forge]\n")
        nested = tmp_path / "src" / "pkg" / "deep"
        nested.mkdir(parents=True)
        found = _find_config_file(nested)
        assert found == cfg_file

    def test_walks_upward_and_stops_at_nearest_file(self, tmp_path: Path):
        parent_file = _write_toml(tmp_path, '[forge]\ndatabase = "parent.db"\n')
        child = tmp_path / "app"
        child.mkdir()
        child_file = _write_toml(child, '[forge]\ndatabase = "child.db"\n')
        nested = child / "nested"
        nested.mkdir()
        found = _find_config_file(nested)
        assert found == child_file
        assert found != parent_file

    def test_returns_none_when_no_config_in_tree(self, tmp_path: Path):
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        found = _find_config_file(nested)
        if found is not None:
            assert not str(found).startswith(str(tmp_path))


# ── load_config ──────────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_missing_forge_toml_returns_defaults(self, tmp_path: Path):
        nested = tmp_path / "project"
        nested.mkdir()
        cfg = load_config(search_dir=nested, environment={})
        assert cfg == ForgeConfig()

    def test_load_explicit_path(self, tmp_path: Path):
        toml_file = _write_toml(
            tmp_path,
            '[forge]\ndatabase = "test.db"\nworkers = 3\n',
            name="myconfig.toml",
        )
        cfg = load_config(path=toml_file, environment={})
        assert Path(cfg.database) == tmp_path / "test.db"
        assert cfg.workers == 3

    def test_load_explicit_path_not_found_raises(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(path=tmp_path / "nonexistent.toml", environment={})

    def test_load_from_nested_discovery(self, tmp_path: Path):
        _write_toml(
            tmp_path,
            '[forge]\ndatabase = ".forge/run.db"\nworkers = 2\n',
        )
        nested = tmp_path / "pkg" / "inner"
        nested.mkdir(parents=True)
        cfg = load_config(search_dir=nested, environment={})
        assert Path(cfg.database) == (tmp_path / ".forge" / "run.db").resolve()
        assert cfg.workers == 2

    def test_load_logging_section(self, tmp_path: Path):
        toml_file = _write_toml(
            tmp_path,
            '[forge]\ndatabase = "out.db"\n\n[logging]\nlevel = "debug"\n',
        )
        cfg = load_config(path=toml_file, environment={})
        assert cfg.log_level == "DEBUG"

    def test_load_forge_config_env_file(self, tmp_path: Path):
        toml_file = _write_toml(
            tmp_path,
            '[forge]\ndatabase = "env.db"\n',
            name="env_config.toml",
        )
        cfg = load_config(
            search_dir=tmp_path / "some" / "subdir",
            environment={"FORGE_CONFIG": str(toml_file)},
        )
        assert Path(cfg.database) == tmp_path / "env.db"

    def test_load_env_var_not_found_raises(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="FORGE_CONFIG"):
            load_config(
                environment={"FORGE_CONFIG": str(tmp_path / "missing.toml")}
            )

    def test_load_malformed_toml_raises(self, tmp_path: Path):
        toml_file = _write_toml(tmp_path, "this is not valid toml !!!\n[[[")
        with pytest.raises(ConfigError, match="Failed to parse"):
            load_config(path=toml_file, environment={})

    def test_load_invalid_workers_value_raises(self, tmp_path: Path):
        toml_file = _write_toml(tmp_path, "[forge]\nworkers = -5\n")
        with pytest.raises(ConfigError, match="Invalid value"):
            load_config(path=toml_file, environment={})

    def test_load_wrong_workers_type_raises(self, tmp_path: Path):
        toml_file = _write_toml(tmp_path, '[forge]\nworkers = "four"\n')
        with pytest.raises(ConfigError, match="Invalid value"):
            load_config(path=toml_file, environment={})

    def test_load_wrong_database_type_raises(self, tmp_path: Path):
        toml_file = _write_toml(tmp_path, "[forge]\ndatabase = 99\n")
        with pytest.raises(ConfigError, match="Invalid value"):
            load_config(path=toml_file, environment={})

    def test_explicit_path_beats_env_var(self, tmp_path: Path):
        explicit = _write_toml(
            tmp_path, '[forge]\ndatabase = "explicit.db"\n', name="explicit.toml"
        )
        env_file = _write_toml(
            tmp_path, '[forge]\ndatabase = "env.db"\n', name="env.toml"
        )
        cfg = load_config(
            path=explicit,
            environment={"FORGE_CONFIG": str(env_file)},
        )
        assert Path(cfg.database) == tmp_path / "explicit.db"

    def test_empty_forge_section(self, tmp_path: Path):
        toml_file = _write_toml(tmp_path, "[forge]\n")
        cfg = load_config(path=toml_file, environment={})
        assert cfg.workers == 1
        assert cfg.database is None

    def test_no_forge_section_at_all(self, tmp_path: Path):
        toml_file = _write_toml(tmp_path, "[other_tool]\nsome_key = 1\n")
        cfg = load_config(path=toml_file, environment={})
        assert cfg == ForgeConfig()


# ── resolve_config precedence ────────────────────────────────────────────────

class TestResolveConfig:
    def test_builtin_defaults_when_nothing_provided(self, tmp_path: Path):
        settings = resolve_config(cwd=tmp_path, environment={}, cli_args={})
        assert settings == ForgeConfig()

    def test_toml_overrides_defaults(self, tmp_path: Path):
        _write_toml(tmp_path, '[forge]\ndatabase = ".forge/forge.db"\nworkers = 4\n')
        settings = resolve_config(cwd=tmp_path, environment={}, cli_args={})
        assert Path(settings.database) == (tmp_path / ".forge" / "forge.db").resolve()
        assert settings.workers == 4

    def test_environment_overrides_toml(self, tmp_path: Path):
        _write_toml(tmp_path, '[forge]\ndatabase = "toml.db"\nworkers = 4\n')
        env_db = tmp_path / "env.db"
        settings = resolve_config(
            cwd=tmp_path,
            environment={"FORGE_DATABASE": str(env_db), "FORGE_WORKERS": "8"},
            cli_args={},
        )
        assert Path(settings.database) == env_db
        assert settings.workers == 8

    def test_cli_overrides_environment(self, tmp_path: Path):
        _write_toml(tmp_path, '[forge]\ndatabase = "toml.db"\nworkers = 4\n')
        env_db = tmp_path / "env.db"
        cli_db = tmp_path / "cli.db"
        settings = resolve_config(
            cwd=tmp_path,
            environment={"FORGE_DATABASE": str(env_db), "FORGE_WORKERS": "8"},
            cli_args={"db": str(cli_db), "workers": 12},
        )
        assert Path(settings.database) == cli_db
        assert settings.workers == 12

    def test_omitted_cli_does_not_override_env(self, tmp_path: Path):
        _write_toml(tmp_path, "[forge]\nworkers = 4\n")
        settings = resolve_config(
            cwd=tmp_path,
            environment={"FORGE_WORKERS": "8"},
            cli_args={"db": None, "workers": None},
        )
        assert settings.workers == 8

    def test_invalid_env_workers_raises(self, tmp_path: Path):
        with pytest.raises(ConfigError, match="FORGE_WORKERS"):
            resolve_config(
                cwd=tmp_path,
                environment={"FORGE_WORKERS": "nope"},
                cli_args={},
            )

    def test_nested_cwd_discovers_toml(self, tmp_path: Path):
        _write_toml(tmp_path, "[forge]\nworkers = 4\n")
        nested = tmp_path / "src" / "inner"
        nested.mkdir(parents=True)
        settings = resolve_config(cwd=nested, environment={}, cli_args={})
        assert settings.workers == 4


# ── CLI Config Integration ───────────────────────────────────────────────────

class TestCLIConfigIntegration:
    def test_run_uses_config_database(self, tmp_path: Path):
        workflow_file = _write_workflow(tmp_path)
        db_path = tmp_path / ".forge" / "auto.db"
        _write_toml(
            tmp_path,
            f'[forge]\ndatabase = "{db_path.as_posix()}"\nworkers = 1\n',
        )

        proc = subprocess.run(
            [sys.executable, "-m", "forge.cli.main", "run", str(workflow_file), "-q"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=_clean_env(),
        )
        assert proc.returncode == 0, proc.stderr
        assert db_path.exists(), "DB should have been created from forge.toml config"

    def test_cli_db_flag_overrides_config(self, tmp_path: Path):
        workflow_file = _write_workflow(tmp_path)
        config_db = tmp_path / "config.db"
        cli_db = tmp_path / "cli_override.db"
        _write_toml(tmp_path, f'[forge]\ndatabase = "{config_db.as_posix()}"\n')

        proc = subprocess.run(
            [
                sys.executable, "-m", "forge.cli.main",
                "run", str(workflow_file),
                "--db", str(cli_db),
                "-q",
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            env=_clean_env(),
        )
        assert proc.returncode == 0, proc.stderr
        assert cli_db.exists(), "CLI --db should win over forge.toml"
        assert not config_db.exists(), "Config DB should not be created when CLI overrides"

    def test_cli_workers_override_environment(self, tmp_path: Path):
        _write_toml(tmp_path, "[forge]\nworkers = 4\n")
        settings = resolve_config(
            cwd=tmp_path,
            environment={"FORGE_WORKERS": "8"},
            cli_args={"workers": 12, "db": None},
        )
        assert settings.workers == 12

    def test_invalid_toml_fails_cli(self, tmp_path: Path, monkeypatch, capsys):
        _write_toml(tmp_path, "[[[ not toml")
        _write_workflow(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_CONFIG", raising=False)
        monkeypatch.delenv("FORGE_DATABASE", raising=False)
        monkeypatch.delenv("FORGE_WORKERS", raising=False)
        code = main(["run", "wf.py", "-q"])
        assert code == 2
        captured = capsys.readouterr()
        assert "Failed to parse" in captured.err

    def test_history_json_is_pure_json(self, tmp_path: Path, monkeypatch, capsys):
        workflow = _write_workflow(tmp_path)
        db_path = tmp_path / "runs.db"
        run_command(workflow, db_path=db_path, quiet=True)
        capsys.readouterr()

        monkeypatch.chdir(tmp_path)
        code = main(["history", "--db", str(db_path), "--json"])
        assert code == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert isinstance(payload, list)
        assert payload[0]["workflow_name"] == "ConfigWF"
        assert captured.out.strip() == json.dumps(payload, indent=2)

    def test_inspect_json_is_pure_json(self, tmp_path: Path, monkeypatch, capsys):
        workflow = _write_workflow(tmp_path)
        db_path = tmp_path / "runs.db"
        run_command(workflow, db_path=db_path, quiet=True)
        store = ExecutionStore.create(db_path)
        run_id = store.list_workflow_runs()[0].run_id
        store.close()
        capsys.readouterr()

        monkeypatch.chdir(tmp_path)
        code = main(["inspect", run_id, "--db", str(db_path), "--json"])
        assert code == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["run_id"] == run_id
        assert payload["workflow_name"] == "ConfigWF"
        assert "tasks" in payload

    def test_status_uses_discovered_db(self, tmp_path: Path, monkeypatch, capsys):
        workflow = _write_workflow(tmp_path)
        db_path = tmp_path / ".forge" / "forge.db"
        _write_toml(tmp_path, '[forge]\ndatabase = ".forge/forge.db"\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_DATABASE", raising=False)
        monkeypatch.delenv("FORGE_CONFIG", raising=False)
        monkeypatch.delenv("FORGE_WORKERS", raising=False)

        assert main(["run", str(workflow), "-q"]) == 0
        assert db_path.exists()
        capsys.readouterr()

        nested = tmp_path / "src"
        nested.mkdir()
        monkeypatch.chdir(nested)
        code = main(["status", "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["exists"] is True
        assert payload["runs"] == 1
        assert Path(payload["database"]) == db_path.resolve()

    def test_status_uses_explicit_db(self, tmp_path: Path, monkeypatch, capsys):
        workflow = _write_workflow(tmp_path)
        toml_db = tmp_path / "toml.db"
        explicit_db = tmp_path / "explicit.db"
        _write_toml(tmp_path, f'[forge]\ndatabase = "{toml_db.as_posix()}"\n')
        run_command(workflow, db_path=explicit_db, quiet=True)
        capsys.readouterr()

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_DATABASE", raising=False)
        monkeypatch.delenv("FORGE_CONFIG", raising=False)
        code = main(["status", "--db", str(explicit_db), "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["exists"] is True
        assert payload["runs"] == 1
        assert Path(payload["database"]) == explicit_db
        assert not toml_db.exists()

    def test_status_json_missing_db_is_valid(self, tmp_path: Path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("FORGE_DATABASE", raising=False)
        monkeypatch.delenv("FORGE_CONFIG", raising=False)
        code = main(["status", "--json"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["exists"] is False
        assert payload["runs"] == 0
        assert payload["recent_runs"] == []


# ── Logging Configuration Tests ───────────────────────────────────────────────

class TestLoggingConfiguration:
    def test_forge_config_logging_fields(self):
        cfg = ForgeConfig(log_level="DEBUG", log_format="json", log_file="forge.log")
        assert cfg.log_level == "DEBUG"
        assert cfg.log_format == "json"
        assert cfg.log_file == "forge.log"

    def test_forge_config_from_dict_logging(self):
        cfg = ForgeConfig.from_dict({
            "log_level": "warning",
            "log_format": "JSON",
            "log_file": "app.log",
        })
        assert cfg.log_level == "WARNING"
        assert cfg.log_format == "json"
        assert cfg.log_file == "app.log"

    def test_forge_config_from_dict_invalid_log_level(self):
        with pytest.raises(ValueError, match="invalid log_level"):
            ForgeConfig.from_dict({"log_level": "INVALID_LEVEL"})

    def test_forge_config_from_dict_invalid_log_format(self):
        with pytest.raises(ValueError, match="invalid log_format"):
            ForgeConfig.from_dict({"log_format": "xml"})

    def test_load_config_logging_section_toml(self, tmp_path: Path):
        toml_path = _write_toml(
            tmp_path,
            '[forge]\nworkers = 2\n\n[logging]\nlevel = "DEBUG"\nformat = "json"\nfile = "forge.log"\n',
        )
        cfg = load_config(toml_path)
        assert cfg.workers == 2
        assert cfg.log_level == "DEBUG"
        assert cfg.log_format == "json"
        assert cfg.log_file == str((tmp_path / "forge.log").resolve())

    def test_resolve_config_logging_precedence(self, tmp_path: Path):
        toml_path = _write_toml(
            tmp_path,
            '[logging]\nlevel = "INFO"\nformat = "text"\nfile = "toml.log"\n',
        )
        # 1. TOML values
        cfg1 = resolve_config(path=toml_path)
        assert cfg1.log_level == "INFO"
        assert cfg1.log_format == "text"

        # 2. Env overlay
        env = {
            "FORGE_LOG_LEVEL": "WARNING",
            "FORGE_LOG_FORMAT": "json",
            "FORGE_LOG_FILE": "env.log",
        }
        cfg2 = resolve_config(path=toml_path, environment=env)
        assert cfg2.log_level == "WARNING"
        assert cfg2.log_format == "json"

        # 3. CLI override overlay
        cli = {
            "log_level": "ERROR",
            "log_format": "text",
            "log_file": "cli.log",
        }
        cfg3 = resolve_config(path=toml_path, environment=env, cli_args=cli)
        assert cfg3.log_level == "ERROR"
        assert cfg3.log_format == "text"

