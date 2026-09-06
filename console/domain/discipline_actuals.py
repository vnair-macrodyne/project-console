"""
DisciplineActuals — actual labour hours/cost by discipline (ETO entity).
A Project Console object assembled from several ETO tables joined behind the view
`vwTimecards` (timecards + hour-types + department), then re-coded to disciplines via
the SHARED HourType→discipline map — the SAME map the budget (EtoBudgetDAO) uses.
The consumer sees one object per project, never the underlying tables.
Cost = applied-rate basis (HourTime × HourRate × HourFactor).

DISCIPLINE CLASSIFICATION — SINGLE SOURCE OF TRUTH (2026-09-06)
    Both sides of every budget-vs-actual comparison classify disciplines through ONE
    map: {HourType(int): discipline}, from Reporting.tlkpHourTypeDiscipline (the store,
    with manual overrides), falling back to the ETO-derived rule. HourType is a
    CONTROLLED key (~58 types) carried by BOTH tblSpecHours (budget) and vwTimecards
    (actual), so the two reconcile line-for-line and any re-code (e.g. shop-floor
    Start-Up → Manufacturing, sql/012) or manual override applies identically to budget
    and actual automatically — no second map to keep in sync.

    (Superseded: actuals used to group vwTimecards by the free-text HourDescription and
    map through a separately-derived description crosswalk. That worked when the rule and
    the store agreed, but silently diverged from the budget whenever the store carried an
    override or a direct re-code the rule could not reproduce. Keying on HourType removes
    that whole class of drift.)
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
    """All SQL for the DisciplineActuals entity. Classifies actuals through the shared
    {HourType: discipline} map (the SAME object the budget uses) so budget and actual
    share ONE discipline definition across every budget-vs-actual report."""

    def __init__(self, eto_conn, hourtype_map: dict):
        """hourtype_map: {HourType(int): discipline} — the shared store-backed map
        (Reporting.tlkpHourTypeDiscipline, else derived from ETO). Same object passed to
        EtoBudgetDAO, so both sides classify identically and honor the same re-codes."""
        self._conn = eto_conn
        self._map = hourtype_map or {}

    def for_projects(self, project_ids) -> dict:
        """{project_id: ProjectDisciplineActuals}."""
        if not project_ids:
            return {}
        ids = ",".join(str(int(p)) for p in project_ids)
        try:
            cur = self._conn.cursor()
            cur.execute(f"""
                SELECT t.ProjectID, ISNULL(t.HourType, 0) AS HourType,
                       SUM(t.HourTime) AS Hours,
                       SUM(t.HourTime * t.HourRate * t.HourFactor) AS Cost
                FROM dbo.vwTimecards t
                WHERE t.ProjectID IN ({ids})
                GROUP BY t.ProjectID, ISNULL(t.HourType, 0)
            """)
            rows = cur.fetchall()
        except Exception as e:
            log.error("discipline actuals read failed: %s", e)
            raise EtoReadError("Failed to read discipline actuals from ETO") from e

        # aggregate by discipline via the SHARED HourType map (same as the budget)
        acc = {}   # pid -> discipline -> [hours, cost]
        for pid, ht, hrs, cost in rows:
            disc = self._map.get(int(ht) if ht is not None else 0, _UNMAPPED)
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
        log.info("assembled discipline actuals for %d projects (HourType-keyed)", len(out))
        return out
