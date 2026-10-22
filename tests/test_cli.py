"""
The command-line entry point, and the promises the 2.0.0 restructure made.

Before 2.0.0 every step was a script at the repo root that put its own folder
on sys.path. These tests pin what replaced that: one registry of commands, a
package that imports without an install, subprocesses that find it the same
way, and one version number everywhere it is written down.
"""
import importlib
import json
import os
import re
import subprocess
import sys

import pytest

from mtg_data import __version__, cli
from mtg_data.core import paths

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.mark.parametrize("command,module_name", sorted(cli.COMMANDS.items()))
def test_every_command_imports_and_has_a_main(command, module_name):
    module = importlib.import_module(module_name)
    assert callable(getattr(module, "main", None)), f"{module_name} has no main()"


def test_command_names_follow_their_modules():
    """A command is its module's name with hyphens, so nobody needs a lookup table.

    2.0.0 renamed mtg_era to era and mtg_fetch to fetch_melee so this holds
    for every command without exceptions.
    """
    for command, module_name in cli.COMMANDS.items():
        assert command == module_name.rsplit(".", 1)[1].replace("_", "-"), command


def test_every_module_with_a_main_is_reachable_from_the_cli():
    """A step you can only run by knowing its file path is a step nobody runs."""
    src = os.path.join(REPO_DIR, "src", "mtg_data")
    reachable = set(cli.COMMANDS.values())
    missing = []
    for dirpath, _dirs, files in os.walk(src):
        for name in files:
            if not name.endswith(".py") or name.startswith("__") or name == "cli.py":
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8") as fh:
                if not re.search(r"^def main\(", fh.read(), re.M):
                    continue
            rel = os.path.relpath(path, os.path.join(REPO_DIR, "src"))
            module_name = rel[:-3].replace(os.sep, ".")
            if module_name not in reachable:
                missing.append(module_name)
    assert not missing, f"modules with a main() but no command: {missing}"


def test_help_lists_every_command(capsys):
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    for command in cli.COMMANDS:
        assert command in out


def test_an_unknown_command_fails_and_suggests(capsys):
    assert cli.main(["validate-event"]) == 2
    err = capsys.readouterr().err
    assert "validate-events" in err


def test_the_pipeline_can_call_itself_without_an_install(tmp_path):
    """fetch-melee runs the scraper, the validator and the auditor as
    `python -m mtg_data <command>` subprocesses. That has to work from any
    working directory on a checkout nobody has pip-installed."""
    env = paths.subprocess_env({k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    env["MTG_DATA_DIR"] = str(tmp_path)
    result = subprocess.run([sys.executable, "-m", "mtg_data", "era", "--json"],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "start" in json.loads(result.stdout)["current"]


def test_the_checkout_launcher_runs(tmp_path):
    result = subprocess.run([sys.executable, os.path.join(REPO_DIR, "mtg.py"), "--version"],
                            cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == __version__


def test_paths_point_at_the_checkout():
    assert os.path.isfile(os.path.join(paths.ROOT_DIR, "mtg.py"))
    assert os.path.isfile(os.path.join(paths.CONFIG_DIR, "bans.json"))
    assert paths.config_path("bans.json") == os.path.join(paths.CONFIG_DIR, "bans.json")


def test_a_data_folder_can_override_shipped_config(tmp_path):
    (tmp_path / "set_releases.json").write_text("{}", encoding="utf-8")
    assert paths.config_path("set_releases.json", str(tmp_path)) == str(tmp_path / "set_releases.json")
    assert paths.config_path("bans.json", str(tmp_path)).startswith(paths.CONFIG_DIR)


def test_one_version_everywhere():
    """The package, the plugin manifest and the marketplace entry carry one version."""
    with open(os.path.join(REPO_DIR, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
        plugin = json.load(fh)["version"]
    with open(os.path.join(REPO_DIR, ".claude-plugin", "marketplace.json"), encoding="utf-8") as fh:
        market = json.load(fh)["plugins"][0]["version"]
    assert __version__ == plugin == market, (__version__, plugin, market)
