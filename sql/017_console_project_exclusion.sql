-- 017_console_project_exclusion.sql
-- "Remove from Console" — a REVERSIBLE soft-exclusion list. A project stays fully intact
-- (its banked budget in tblProjectBudget and its plan/progress rows are untouched); it is
-- simply hidden from the console's tracked-project set. Re-adding it (PM "Add to Console")
-- deletes its exclusion row and it reappears with all history.
--
-- Consumers filter tracked projects through this list:
--   queries.py  LiveQueryService.list_projects   (the main project selector / dashboards / display)
--   pm.py       LivePMService._budgeted_ids
--   plan.py     LivePlanService._budgeted_ids
-- All three read it defensively, so the app still runs if this migration hasn't been applied.
--
-- Idempotent.

IF NOT EXISTS (SELECT 1 FROM sys.tables t
               JOIN sys.schemas s ON s.schema_id = t.schema_id
               WHERE s.name = 'Reporting' AND t.name = 'tblConsoleProjectExclusion')
BEGIN
    CREATE TABLE Reporting.tblConsoleProjectExclusion (
        ProjectID   INT           NOT NULL PRIMARY KEY,
        ExcludedAt  DATETIME      NOT NULL CONSTRAINT DF_ConsoleProjExcl_At DEFAULT (GETDATE()),
        ExcludedBy  NVARCHAR(128) NULL
    );
END
GO
