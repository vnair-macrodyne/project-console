"""
Project Console — typed exception hierarchy.
All layers raise these; nothing swallows. DAOs wrap driver errors into these so the
service/orchestration layer catches Console errors, not pyodbc internals.
"""


class ConsoleError(Exception):
    """Base for every Project Console error."""


class ConfigError(ConsoleError):
    """Missing/invalid tenant configuration or credentials."""


class ConnectionFailed(ConsoleError):
    """Could not open a database connection (ETO or Console)."""


class EtoReadError(ConsoleError):
    """A read against the vendor ETO database failed."""


class StoreReadError(ConsoleError):
    """A read against the Console store failed."""


class StoreWriteError(ConsoleError):
    """A write against the Console store failed."""


class EntityNotFound(ConsoleError):
    """A requested entity does not exist."""


class DataValidationError(ConsoleError):
    """Loaded/assembled data failed a domain validation rule."""
