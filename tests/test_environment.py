"""CONSOLE_ENV resolution: every env maps to its own Reporting DB; typos never reach prod."""
import pytest

import console_config as cfg


@pytest.mark.parametrize("raw,expected", [
    ("dev", "dev"), ("Staging", "staging"), (" prod ", "prod"), (None, "dev"),
])
def test_resolve_known(raw: str | None, expected: str) -> None:
    assert cfg.resolve_environment(raw) == expected


@pytest.mark.parametrize("raw", ["", "test", "stage", "production"])
def test_resolve_unknown_raises(raw: str) -> None:
    with pytest.raises(cfg.UnknownEnvironment):
        cfg.resolve_environment(raw)


def test_each_env_has_its_own_store() -> None:
    named = [db for db in cfg.ENV_STORE_DB.values() if db is not None]
    assert len(named) == len(set(named))
    assert cfg.ENV_STORE_DB["dev"] == "Macrodyne_Reporting_Dev"
