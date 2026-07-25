"""
DisciplineActuals — actual labour hours/cost by discipline (ETO entity).
A Project Console object assembled from several ETO tables joined behind the view
`vwTimecards` (timecards + hour-types + department), then re-coded to disciplines via
the crosswalk. The consumer sees one object per project, never the underlying tables.
Cost = applied-rate basis (HourTime × HourRate × HourFactor).
"""
from dataclasses import dataclass, field

from console.infra.errors import EtoReadError
from console.infra.logging_config import get_logger

log = get_logger(__name__)

_UNMAPPED = "Other"


@dataclass(frozen=True)
class DisciplineActual:
    discipline: str
    actual_hours: float
    actual_cost: float


@dataclass
class ProjectDisciplineActuals:
    """All disciplines' actuals for one project."""
    project_id: int
    by_discipline: dict = field(default_factory=dict)   # discipline -> DisciplineActual

    def hours(self, discipline: str):
        a = self.by_discipline.get(discipline)
        return a.actual_hours if a else None

    def total_hours(self) -> float:
        return round(sum(a.actual_hours for a in self.by_discipline.values()), 2)


class DisciplineActualsDAO:
    """All SQL for the DisciplineActuals entity. Applies the crosswalk (Console) to the
    ETO reads so budget and actual share one discipline mapping."""

    def __init__(self, eto_conn, crosswalk: dict):
        self._conn = eto_conn
        self._xwalk = crosswalk or {}

    def for_projects(self, project_ids) -> dict:
        """{project_id: ProjectDisciplineActuals}."""
        if not project_ids:
            return {}
        ids = ",".join(str(int(p)) for p in project_ids)
        try:
            cur = self._conn.cursor()
            cur.execute(f"""
                SELECT t.ProjectID, t.HourDescription,
                       SUM(t.HourTime) AS Hours,
                       SUM(t.HourTime * t.HourRate * t.HourFactor) AS Cost
                FROM dbo.vwTimecards t
                WHERE t.ProjectID IN ({ids})
                GROUP BY t.ProjectID, t.HourDescription
            """)
            rows = cur.fetchall()
        except Exception as e:
            log.error("discipline actuals read failed: %s", e)
            raise EtoReadError("Failed to read discipline actuals from ETO") from e

        # aggregate by discipline via the crosswalk
        acc = {}   # pid -> discipline -> [hours, cost]
        for pid, hd, hrs, cost in rows:
            disc = self._xwalk.get(hd, _UNMAPPED)
            d = acc.setdefault(int(pid), {})
            slot = d.setdefault(disc, [0.0, 0.0])
            slot[0] += float(hrs or 0)
            slot[1] += float(cost or 0)
        out = {}
        for pid, discs in acc.items():
            out[pid] = ProjectDisciplineActuals(
                project_id=pid,
                by_discipline={disc: DisciplineActual(disc, round(h, 2), round(c, 2))
                               for disc, (h, c) in discs.items()})
        log.info("assembled discipline actuals for %d projects", len(out))
        return out
