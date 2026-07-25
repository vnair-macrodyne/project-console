"""
DisciplineCrosswalk — the HourDescription → discipline mapping (reference entity).
Source: Console store (Reporting.tlkpDisciplineCrosswalk). Single source of truth so
budget roll-ups and ETO actual re-codes share one mapping.
"""
from dataclasses import dataclass

from console.infra.errors import StoreReadError, StoreWriteError
from console.infra.logging_config import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class DisciplineMapping:
    hour_description: str
    discipline: str


class CrosswalkDAO:
    """All SQL for the crosswalk entity. Returns DOs / a plain lookup dict."""

    def __init__(self, console_conn):
        self._conn = console_conn

    def load_map(self) -> dict:
        """{HourDescription: discipline} for applying to ETO actuals."""
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT HourDescription, Discipline "
                        "FROM Reporting.tlkpDisciplineCrosswalk")
            return {r[0]: r[1] for r in cur.fetchall()}
        except Exception as e:
            log.error("crosswalk load failed: %s", e)
            raise StoreReadError("Failed to load discipline crosswalk") from e

    def list(self) -> list:
        return [DisciplineMapping(hd, d) for hd, d in self.load_map().items()]

    def replace(self, mappings) -> int:
        """Replace the crosswalk (delete + insert). `mappings`: iterable of
        (hour_description, discipline) or DisciplineMapping. Returns rows written."""
        rows = [(m.hour_description, m.discipline) if isinstance(m, DisciplineMapping)
                else (m[0], m[1]) for m in mappings]
        try:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM Reporting.tlkpDisciplineCrosswalk")
            cur.executemany(
                "INSERT INTO Reporting.tlkpDisciplineCrosswalk(HourDescription, Discipline) "
                "VALUES (?, ?)", rows)
            self._conn.commit()
            log.info("crosswalk replaced: %d mappings", len(rows))
            return len(rows)
        except Exception as e:
            self._conn.rollback()
            log.error("crosswalk replace failed: %s", e)
            raise StoreWriteError("Failed to replace discipline crosswalk") from e
