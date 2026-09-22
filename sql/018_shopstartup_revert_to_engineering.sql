/*==============================================================================
  018_shopstartup_revert_to_engineering.sql — put Shop Start-Up back under Engineering

  Decision (Vijay, 2026-09-22, from Mike Plata's feedback): ETO books "Electrical Shop
  Start-Up" and "Hydraulic Shop Start-Up" under the ENGINEERING department, and its printed
  Structured-BOM / estimate report groups them there. The console must match ETO, so these
  hours go back to their engineering discipline. This REVERSES 012_shopstartup_to_manufacturing.sql.

  PRECISION: the pattern is '%Shop Start%' ONLY — deliberately NOT the broader '%Start-Up%' /
  '%Start Up%' that 012 used — because ETO's Manufacturing department has a legitimate
  "Start-up/Testing" line that must STAY in Manufacturing. Every engineering start-up line
  ("... Shop Start-Up") contains "Shop Start"; "Start-up/Testing" does not. Non-'manual' rows
  only (human overrides preserved). Idempotent.

  Discipline is restored by description keyword: hydraul -> Hydraulic Engineering;
  electr/program -> Electrical Engineering; else Mechanical Engineering — the same split the
  runtime rule (console/domain/hourtype_map.discipline_for) now applies.

  CANONICAL ALTERNATIVE (preferred where the app host can reach BOTH stores): after deploying
  the matching console/domain/hourtype_map.py, run  `python console_seed_hourtype.py`  — it
  re-derives every non-manual row straight from ETO's HourDepartment through the corrected rule,
  which is exact (no keyword edge cases) and also refreshes any other drifted rows.

  Run against the Console store; then deploy hourtype_map.py and restart (each request loads the
  map fresh, so a rebuild/redeploy is enough).
==============================================================================*/

-- BUDGET/ACTUAL map: HourType -> discipline (008_hourtype_discipline.sql)
IF OBJECT_ID('Reporting.tlkpHourTypeDiscipline', 'U') IS NOT NULL
    UPDATE Reporting.tlkpHourTypeDiscipline
    SET Discipline = CASE
            WHEN HourDescription LIKE '%hydraul%'                                  THEN 'Hydraulic Engineering'
            WHEN HourDescription LIKE '%electr%' OR HourDescription LIKE '%program%' THEN 'Electrical Engineering'
            ELSE 'Mechanical Engineering' END,
        UpdatedAt = GETDATE()
    WHERE ISNULL(Source, 'ETO') <> 'manual'
      AND Discipline = 'Manufacturing'
      AND HourDescription LIKE '%Shop Start%';
GO

-- Legacy display crosswalk: HourDescription -> discipline (shown by the Crosswalk report)
IF OBJECT_ID('Reporting.tlkpDisciplineCrosswalk', 'U') IS NOT NULL
    UPDATE Reporting.tlkpDisciplineCrosswalk
    SET Discipline = CASE
            WHEN HourDescription LIKE '%hydraul%'                                  THEN 'Hydraulic Engineering'
            WHEN HourDescription LIKE '%electr%' OR HourDescription LIKE '%program%' THEN 'Electrical Engineering'
            ELSE 'Mechanical Engineering' END
    WHERE Discipline = 'Manufacturing'
      AND HourDescription LIKE '%Shop Start%';
GO
