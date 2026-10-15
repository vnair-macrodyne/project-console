-- 020_active_project.sql
-- Reporting.tblActiveProject — the ACTIVE / open project list that Purchasing works from.
-- Source of truth is the "Worksheet" tab of the Executive Dashboard (maintained by Helen Young
-- and Mike Plata). Refreshed by console_seed_active_project.py (full DELETE + reinsert from the
-- sheet). Presence in this table = the project is active; Priority is the sheet's sequence number.
--
-- Planned consumers:
--   queries.py  — the "Purchasing Exception Report" (renamed All Purchase Orders) filters PO lines
--                 to projects IN this table.
--   the tracked-project set — "ensure these are active on Sextant" reconciles the console's tracked
--                 projects against this list.
-- Read consumers should read it defensively, so the app still runs if this migration/seed hasn't run.
--
-- Idempotent.

IF NOT EXISTS (SELECT 1 FROM sys.tables t
               JOIN sys.schemas s ON s.schema_id = t.schema_id
               WHERE s.name = 'Reporting' AND t.name = 'tblActiveProject')
BEGIN
    CREATE TABLE Reporting.tblActiveProject (
        ProjectID   INT           NOT NULL PRIMARY KEY,
        Customer    NVARCHAR(200) NULL,
        Priority    INT           NULL,        -- sequence from the sheet (1..n); NULL = unsequenced
        Source      NVARCHAR(100) NOT NULL CONSTRAINT DF_ActiveProject_Source     DEFAULT ('ExecDashboard/Worksheet'),
        ImportedAt  DATETIME      NOT NULL CONSTRAINT DF_ActiveProject_ImportedAt DEFAULT (GETDATE())
    );
END
GO

-- Run once as owner if the app/seed login lacks CREATE on the locked-down Reporting DB, then grant:
-- GRANT SELECT, INSERT, DELETE ON Reporting.tblActiveProject TO [<app login>];
