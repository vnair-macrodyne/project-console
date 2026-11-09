-- 022_tracked_projects.sql
-- Tracked Projects — Sextant becomes the place the active / tracked project list is kept
-- (Vijay, 2026-11-09). Replaces the PMs' "Worksheet" tab of the Executive Dashboard workbook.
--
-- ONE switch: Reporting.tblActiveProject.IsActive. A tracked project (IsActive = 1) is in the
-- project selector, the dashboards, the display screens and the Purchasing Exception Report.
-- Removing a project sets IsActive = 0 and keeps the row (and its budget / plan history), so
-- re-adding restores it. Removal also writes the sql/017 exclusion row so every older filter
-- agrees; re-adding clears it. Writes go through console/domain/tracked.py only.
--
-- Priority = the PMs' sequence (1..n among tracked projects); NULL on removed rows.
-- Customer (sql/020) is no longer written: Sextant reads it live from ETO (tblCompany.CName).
--
-- Reporting.tblTrackedProjectLog = who changed the list, when, and what (add / remove /
-- reorder / seed). Append-only.
--
-- Idempotent. Run once in SSMS as an owner account (the app login has no ALTER/CREATE), then
-- the GRANT at the bottom.

IF COL_LENGTH('Reporting.tblActiveProject', 'IsActive') IS NULL
    ALTER TABLE Reporting.tblActiveProject
        ADD IsActive BIT NOT NULL CONSTRAINT DF_ActiveProject_IsActive DEFAULT (1);
GO
IF COL_LENGTH('Reporting.tblActiveProject', 'AddedBy') IS NULL
    ALTER TABLE Reporting.tblActiveProject ADD AddedBy NVARCHAR(128) NULL;
GO
IF COL_LENGTH('Reporting.tblActiveProject', 'AddedAt') IS NULL
    ALTER TABLE Reporting.tblActiveProject ADD AddedAt DATETIME NULL;
GO
IF COL_LENGTH('Reporting.tblActiveProject', 'ChangedBy') IS NULL
    ALTER TABLE Reporting.tblActiveProject ADD ChangedBy NVARCHAR(128) NULL;
GO
IF COL_LENGTH('Reporting.tblActiveProject', 'ChangedAt') IS NULL
    ALTER TABLE Reporting.tblActiveProject ADD ChangedAt DATETIME NULL;
GO
-- existing (seeded) rows: added = when they were imported
UPDATE Reporting.tblActiveProject SET AddedAt = ImportedAt WHERE AddedAt IS NULL;
GO

IF NOT EXISTS (SELECT 1 FROM sys.tables t
               JOIN sys.schemas s ON s.schema_id = t.schema_id
               WHERE s.name = 'Reporting' AND t.name = 'tblTrackedProjectLog')
BEGIN
    CREATE TABLE Reporting.tblTrackedProjectLog (
        LogID      INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
        ProjectID  INT           NULL,          -- NULL for a whole-list reorder
        Action     NVARCHAR(20)  NOT NULL,      -- add | remove | reorder | seed-add | seed-remove
        Detail     NVARCHAR(1000) NULL,         -- e.g. priority 3 -> 1, or the new order
        ChangedBy  NVARCHAR(128) NULL,
        ChangedAt  DATETIME      NOT NULL CONSTRAINT DF_TrackedLog_At DEFAULT (GETDATE())
    );
END
GO

-- App login needs UPDATE now (it previously had SELECT, INSERT, DELETE):
-- GRANT SELECT, INSERT, UPDATE, DELETE ON Reporting.tblActiveProject     TO [<app login>];
-- GRANT SELECT, INSERT                 ON Reporting.tblTrackedProjectLog TO [<app login>];
-- GRANT SELECT, INSERT, DELETE         ON Reporting.tblConsoleProjectExclusion TO [<app login>];  -- already held
