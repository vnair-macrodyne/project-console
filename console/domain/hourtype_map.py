"""
HourType -> discipline crosswalk (authoritative), anchored to ETO's HourDepartment.

WHY THIS EXISTS
    tblSpecHours.HourDescription is FREE TEXT (estimators type one-off strings per
    line — thousands of variants), so it cannot be crosswalked. But every estimate
    line carries tblSpecHours.HourType, a CONTROLLED key (~58 types), and ETO's
    tlkpHourTypes already classifies each into Admin / Engineering / Manufacturing.
    Mapping HourType -> discipline off that department (Admin->PM, Mfg->Manufacturing,
    Eng->Mechanical/Electrical/Hydraulic by the controlled description) reconciles
    EXACTLY to ETO's 3-bucket estimate, verified 2026-07-27 on 230219/240033/220154
    (delta 0, zero free-text residue).

    This same map is the right key for ACTUALS too (vwTimecards HourType/description),
    replacing the incomplete 39-row spreadsheet-derived crosswalk.

The map is stored in Reporting.tlkpHourTypeDiscipline (008_hourtype_discipline.sql),
seeded from ETO by console_sync. A human may override any row (Source='manual'); the
re-seed preserves overrides. Product core is tenant-agnostic — nothing Macrodyne here.
"""
from console.infra.logging_config import get_logger

log = get_logger(__name__)

DISCIPLINES = ["Project Management", "Mechanical Engineering", "Hydraulic Engineering",
               "Electrical Engineering", "Manufacturing", "Other"]


def discipline_for(dept: str, desc: str) -> str:
    """The rule, anchored to ETO's HourDepartment. NC types -> Other; Admin -> PM;
    Mfg -> Manufacturing; Eng -> Electrical (electr/program) | Hydraulic (hydraul) |
    Mechanical (default)."""
    d = (desc or "").lower()
    dep = (dept or "").strip().lower()
    if "non-conformance" in d or "(nc)" in d:
        return "Other"
    if dep.startswith("admin"):
        return "Project Management"
    if dep.startswith("manuf"):
        return "Manufacturing"
    if dep.startswith("eng"):
        # Shop-floor start-up / commissioning is booked under the Engineering department in ETO,
        # but it's shop work, not design — folding it into Manufacturing keeps the engineering
        # disciplines reflecting DESIGN effort only, so a discipline manager's utilisation matches
        # their engineering budget line (Vijay 2026-08-12; e.g. Hydraulic/Electrical Shop Start-Up).
        if "shop start" in d or "start-up" in d or "start up" in d:
            return "Manufacturing"
        if "hydraul" in d:
            return "Hydraulic Engineering"
        if "electr" in d or "program" in d:
            return "Electrical Engineering"
        return "Mechanical Engineering"
    return "Other"


class HourTypeDisciplineDAO:
    """Load / seed the HourType -> discipline map (Console store)."""

    def __init__(self, store_conn):
        self._c = store_conn

    def load_map(self) -> dict:
        """{HourType(int): discipline} from the store. {} if the table is absent/empty."""
        try:
            cur = self._c.cursor()
            cur.execute("SELECT HourType, Discipline FROM Reporting.tlkpHourTypeDiscipline")
            return {int(r[0]): str(r[1]) for r in cur.fetchall()}
        except Exception as e:
            log.warning("HourType map load failed (%s) — caller should fall back to ETO", e)
            return {}

    def seed_from_eto(self, eto_conn) -> int:
        """Read ETO's tlkpHourTypes, apply the rule, upsert into the store. Rows a human
        set to Source='manual' are preserved. Returns the number of hour types processed."""
        ecur = eto_conn.cursor()
        ecur.execute("SELECT HourType, HourDescription, ISNULL(HourDepartment,'') "
                     "FROM dbo.tlkpHourTypes")
        rows = [(int(ht), desc, discipline_for(dept, desc)) for ht, desc, dept in ecur.fetchall()]
        cur = self._c.cursor()
        for ht, desc, disc in rows:
            cur.execute(
                "MERGE Reporting.tlkpHourTypeDiscipline AS t "
                "USING (SELECT ? AS HourType) AS s ON t.HourType = s.HourType "
                "WHEN MATCHED AND t.Source <> 'manual' THEN "
                "  UPDATE SET HourDescription = ?, Discipline = ?, UpdatedAt = GETDATE() "
                "WHEN NOT MATCHED THEN "
                "  INSERT (HourType, HourDescription, Discipline, Source, UpdatedAt) "
                "  VALUES (?, ?, ?, 'ETO', GETDATE());",
                ht, desc, disc, ht, desc, disc)
        self._c.commit()
        log.info("seeded HourType->discipline map: %d hour types", len(rows))
        return len(rows)

    @staticmethod
    def derive_from_eto(eto_conn) -> dict:
        """{HourType: discipline} computed straight from ETO's tlkpHourTypes + the rule,
        with no store dependency — the runtime fallback when the store table is empty."""
        cur = eto_conn.cursor()
        cur.execute("SELECT HourType, HourDescription, ISNULL(HourDepartment,'') "
                    "FROM dbo.tlkpHourTypes")
        return {int(ht): discipline_for(dept, desc) for ht, desc, dept in cur.fetchall()}

    @staticmethod
    def derive_description_map_from_eto(eto_conn) -> dict:
        """{HourDescription: discipline} for ETO's controlled hour types — the SAME rule
        as the HourType map, so ACTUALS (classified off vwTimecards.HourDescription, which
        is the controlled description) share one definition with the budget. Replaces the
        incomplete 39-row spreadsheet crosswalk for the discipline blocks."""
        cur = eto_conn.cursor()
        cur.execute("SELECT HourDescription, ISNULL(HourDepartment,'') FROM dbo.tlkpHourTypes")
        return {str(desc): discipline_for(dept, desc) for desc, dept in cur.fetchall()}
