/*==============================================================================
  012_shopstartup_to_manufacturing.sql — reclassify shop-floor Start-Up to Manufacturing

  Decision (Vijay, 2026-08-12): "Shop Start-Up" hour types (e.g. Hydraulic Shop Start-Up,
  Electrical Shop Start-Up) are booked under ETO's ENGINEERING department, but they're
  shop-floor commissioning, not design. Folding them into Manufacturing makes each
  engineering discipline reflect DESIGN effort only, so a discipline manager's utilisation
  matches their engineering budget line (250250 Hydraulic: 520 → 420 ⇒ ~74% → ~91%).

  The runtime rule (console/domain/hourtype_map.discipline_for) already does this for ACTUALS
  (derived live) and for BUDGET when derived from ETO. This migration aligns the SEEDED budget
  map (and the legacy display crosswalk) so a store that reads from the table matches too.
  Idempotent. Non-'manual' rows only (human overrides are preserved). Run against the Console
  store; then deploy the matching console/domain/hourtype_map.py and restart.
==============================================================================*/

-- BUDGET map: HourType -> discipline (008_hourtype_discipline.sql)
IF OBJECT_ID('Reporting.tlkpHourTypeDiscipline', 'U') IS NOT NULL
    UPDATE Reporting.tlkpHourTypeDiscipline
    SET Discipline = 'Manufacturing', UpdatedAt = GETDATE()
    WHERE ISNULL(Source, 'ETO') <> 'manual'
      AND Discipline IN ('Electrical Engineering', 'Hydraulic Engineering', 'Mechanical Engineering')
      AND (HourDescription LIKE '%Shop Start%'
           OR HourDescription LIKE '%Start-Up%'
           OR HourDescription LIKE '%Start Up%');
GO

-- Legacy display crosswalk: HourDescription -> discipline (shown by the Crosswalk report)
IF OBJECT_ID('Reporting.tlkpDisciplineCrosswalk', 'U') IS NOT NULL
    UPDATE Reporting.tlkpDisciplineCrosswalk
    SET Discipline = 'Manufacturing'
    WHERE Discipline IN ('Electrical Engineering', 'Hydraulic Engineering', 'Mechanical Engineering')
      AND (HourDescription LIKE '%Shop Start%'
           OR HourDescription LIKE '%Start-Up%'
           OR HourDescription LIKE '%Start Up%');
GO
