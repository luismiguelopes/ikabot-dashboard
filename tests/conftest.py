"""Shared test plumbing (P13.45).

Many tests point db_manager at a temporary database by assigning its module globals
(`_setup_db`, copied in three files, and direct assignments elsewhere). Nothing put them back,
so the database of one test stayed in force for whatever ran next — tests passed or failed
depending on the order. The autouse fixture below restores those globals after EVERY test, and
`setup_db` is the one helper to point db_manager at a fresh database.
"""
import pytest

# Import the REAL ikabot package before any test module is collected. Several test files stub
# `ikabot` in sys.modules "if it is not there yet"; when one of them happened to be collected
# first, the stub (not a package) hid the real one and the next file that needed
# `ikabot.config` failed to import — the suite only worked in alphabetical order.
import importlib

for _mod in ("ikabot", "ikabot.config", "ikabot.helpers", "ikabot.helpers.getJson",
             "ikabot.helpers.naval", "ikabot.helpers.pedirInfo", "ikabot.helpers.planRoutes",
             "ikabot.helpers.process", "ikabot.helpers.signals", "ikabot.helpers.botComm",
             "ikabot.helpers.gui", "ikabot.helpers.varios", "ikabot.web.session"):
    try:
        importlib.import_module(_mod)
    except Exception:        # not importable here: the test files' own stubs take over
        pass

import db_manager

_DB_GLOBALS = ("DB_PATH", "_LOGS_DIR", "_DB_INIT_DONE")


def setup_db(tmp_path, name="test.db"):
    """Point db_manager at a fresh database inside tmp_path (restored by the fixture below)."""
    db_manager.DB_PATH = str(tmp_path / name)
    db_manager._LOGS_DIR = str(tmp_path)
    db_manager._DB_INIT_DONE = False


@pytest.fixture(autouse=True)
def _restore_db_manager_globals():
    saved = {k: getattr(db_manager, k) for k in _DB_GLOBALS if hasattr(db_manager, k)}
    yield
    for k, v in saved.items():
        setattr(db_manager, k, v)


@pytest.fixture
def db(tmp_path):
    """A fresh database for the test; yields db_manager."""
    setup_db(tmp_path)
    return db_manager
