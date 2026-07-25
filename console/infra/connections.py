"""
Project Console — connection factories (the two-connection seam).

Two cleanly separated connections; the Console store never links to ETO. Both wrap
driver failures into typed ConsoleErrors and log context. Swapping the Console store
to another engine (Postgres/cloud) is a change HERE, not in the DAOs.
"""
import os
from contextlib import contextmanager

from console.config import TENANT
from console.infra.errors import ConfigError, ConnectionFailed
from console.infra.logging_config import get_logger

log = get_logger(__name__)


def _connect(conn_str: str, what: str):
    import pyodbc
    try:
        return pyodbc.connect(conn_str)
    except Exception as e:  # pyodbc.Error and friends
        log.error("%s connection failed: %s", what, e)
        raise ConnectionFailed(f"Could not connect to {what}") from e


def eto_connection():
    """READ-ONLY connection to the vendor ETO SQL Server."""
    cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
          f"Database={TENANT.eto_database};")
    if TENANT.use_windows_auth:
        cs += "Trusted_Connection=yes;"
    else:
        u, p = os.environ.get("ETO_USER"), os.environ.get("ETO_PWD")
        if not (u and p):
            raise ConfigError("ETO_USER/ETO_PWD not set for SQL-auth ETO connection")
        cs += f"UID={u};PWD={p};"
    log.debug("opening ETO connection to %s/%s", TENANT.eto_server, TENANT.eto_database)
    return _connect(cs, "ETO")


def console_connection():
    """Read/write connection to the Console store."""
    if not TENANT.use_windows_auth and not (TENANT.reporting_user and TENANT.reporting_pwd):
        raise ConfigError("MACRODYNE_REPORTING_USER/PWD not set for the Console store")
    log.debug("opening Console connection to %s/%s",
              TENANT.reporting_server, TENANT.reporting_database)
    return _connect(TENANT.reporting_conn_str(), "Console store")


@contextmanager
def opened(factory):
    """`with opened(console_connection) as conn:` — always closes, logs failures."""
    conn = factory()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # pragma: no cover
            log.warning("error closing connection", exc_info=True)
