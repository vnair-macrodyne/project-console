-- ============================================================================
-- 003_create_reporting_staging.sql
-- STAGING copy of the Project Console Reporting store, for testing the PM
-- budgeting / planning module (and RBAC) without touching production.
--
-- Same schema as 001 (incl. LatePenalty), in a separate database
--   Macrodyne_Reporting_Staging
-- on the SAME server. The console points at it via env (no code change):
--   CONSOLE_ENV=staging                     (uses this DB name), or
--   CONSOLE_STORE_DB=Macrodyne_Reporting_Staging
-- ETO stays PROD and READ-ONLY — Python reads it over the separate eto_* connection;
-- this staging DB has NO link to the vendor database.
--
-- Run as a MACRODYNE-controlled sysadmin. Idempotent-ish (guards on create).
-- Owner: Vijay Nair (IT).  To make another env, change the DB name throughout.
-- ============================================================================

------------------------------------------------------------------------------
-- 0. Database + schema
------------------------------------------------------------------------------
IF DB_ID('Macrodyne_Reporting_Staging') IS NULL
    CREATE DATABASE Macrodyne_Reporting_Staging;
GO
USE Macrodyne_Reporting_Staging;
GO
IF SCHEMA_ID('Reporting') IS NULL
    EXEC('CREATE SCHEMA Reporting');
GO

------------------------------------------------------------------------------
-- 1. Discipline crosswalk
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.tlkpDisciplineCrosswalk','U') IS NULL
CREATE TABLE Reporting.tlkpDisciplineCrosswalk (
    HourDescription   NVARCHAR(80)  NOT NULL PRIMARY KEY,
    Discipline        NVARCHAR(40)  NOT NULL,
    UpdatedAt         DATETIME      NOT NULL DEFAULT GETDATE()
);
GO

------------------------------------------------------------------------------
-- 1b. Console users (RBAC) — Windows login → role
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.tblConsoleUser','U') IS NULL
CREATE TABLE Reporting.tblConsoleUser (
    Username     NVARCHAR(128) NOT NULL PRIMARY KEY,
    Role         NVARCHAR(20)  NOT NULL DEFAULT 'viewer',
    DisplayName  NVARCHAR(128) NULL,
    UpdatedAt    DATETIME      NOT NULL DEFAULT GETDATE(),
    UpdatedBy    NVARCHAR(128) NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM Reporting.tblConsoleUser WHERE Role='admin')
    INSERT INTO Reporting.tblConsoleUser(Username, Role, DisplayName, UpdatedBy)
    VALUES ('vnair', 'admin', 'Vijay Nair', 'install');
GO

------------------------------------------------------------------------------
-- 2. Budget header (SCD-2) — incl. LatePenalty
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.tblProjectBudget','U') IS NULL
CREATE TABLE Reporting.tblProjectBudget (
    BudgetVersionID     INT IDENTITY(1,1) PRIMARY KEY,
    ProjectID           INT           NOT NULL,
    EffectiveFrom       DATE          NOT NULL,
    EffectiveTo         DATE          NULL,
    IsCurrent           BIT           NOT NULL DEFAULT 1,
    Source              NVARCHAR(60)  NULL,
    POShipDate          DATE          NULL,
    CustAgreedShipDate  DATE          NULL,
    LatePenalty         BIT           NULL,
    MaterialBudget      DECIMAL(14,2) NULL,
    LabourBudgetHours   DECIMAL(12,2) NULL,
    PMHours             DECIMAL(12,2) NULL,
    MechanicalHours     DECIMAL(12,2) NULL,
    ElectricalHours     DECIMAL(12,2) NULL,
    HydraulicHours      DECIMAL(12,2) NULL,
    ManufacturingHours  DECIMAL(12,2) NULL,
    OtherHours          DECIMAL(12,2) NULL,
    CreatedAt           DATETIME      NOT NULL DEFAULT GETDATE(),
    CreatedBy           NVARCHAR(60)  NULL
);
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_ProjectBudget_Current')
CREATE UNIQUE INDEX UX_ProjectBudget_Current
    ON Reporting.tblProjectBudget(ProjectID) WHERE IsCurrent = 1;
GO
IF COL_LENGTH('Reporting.tblProjectBudget','LatePenalty') IS NULL
    ALTER TABLE Reporting.tblProjectBudget ADD LatePenalty BIT NULL;
GO

------------------------------------------------------------------------------
-- 3. Budget detail
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.tblProjectBudgetDetail','U') IS NULL
CREATE TABLE Reporting.tblProjectBudgetDetail (
    BudgetVersionID   INT           NOT NULL
        REFERENCES Reporting.tblProjectBudget(BudgetVersionID),
    HourDescription   NVARCHAR(80)  NOT NULL,
    BudgetHours       DECIMAL(12,2) NULL,
    CONSTRAINT PK_ProjectBudgetDetail PRIMARY KEY (BudgetVersionID, HourDescription)
);
GO

------------------------------------------------------------------------------
-- 4. PM entries (weekly)
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.tblProjectPMEntry','U') IS NULL
CREATE TABLE Reporting.tblProjectPMEntry (
    PMEntryID           INT IDENTITY(1,1) PRIMARY KEY,
    ProjectID           INT           NOT NULL,
    FiscalYear          INT           NULL,
    WeekNo              INT           NULL,
    YearWeekKey         INT           NOT NULL,
    PlannedShipDate     DATE          NULL,
    PercentComplete     DECIMAL(6,4)  NULL,
    LabourRunout        DECIMAL(7,4)  NULL,
    MaterialRunout      DECIMAL(7,4)  NULL,
    MaterialActual      DECIMAL(14,2) NULL,
    MaterialBudget      DECIMAL(14,2) NULL,
    TotalLineItems      INT           NULL,
    LLTPOrdered         INT           NULL,
    LLTPReleasedLate    INT           NULL,
    LLTPOrderedLate     INT           NULL,
    LLTPDeliveredLate   INT           NULL,
    PartsReleasedLate   INT           NULL,
    PartsOrderedLate    INT           NULL,
    Delta1WkPercentDone DECIMAL(7,4)  NULL,
    Delta1WkMaterial    DECIMAL(14,2) NULL,
    IncludeFlag         BIT           NULL,
    Rank                INT           NULL,
    ReRank              INT           NULL,
    CapturedAt          DATETIME      NOT NULL DEFAULT GETDATE(),
    CONSTRAINT UX_PMEntry UNIQUE (ProjectID, YearWeekKey)
);
GO

------------------------------------------------------------------------------
-- 5. Views (identical interface to prod)
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.vw_Console_BudgetCurrent','V') IS NOT NULL DROP VIEW Reporting.vw_Console_BudgetCurrent;
GO
CREATE VIEW Reporting.vw_Console_BudgetCurrent AS
    SELECT * FROM Reporting.tblProjectBudget WHERE IsCurrent = 1;
GO
IF OBJECT_ID('Reporting.vw_Console_PMEntryLatest','V') IS NOT NULL DROP VIEW Reporting.vw_Console_PMEntryLatest;
GO
CREATE VIEW Reporting.vw_Console_PMEntryLatest AS
    SELECT p.* FROM Reporting.tblProjectPMEntry p
    JOIN (SELECT ProjectID, MAX(YearWeekKey) AS mx FROM Reporting.tblProjectPMEntry
          WHERE IncludeFlag = 1 GROUP BY ProjectID) m
      ON p.ProjectID = m.ProjectID AND p.YearWeekKey = m.mx;
GO
IF OBJECT_ID('Reporting.vw_Console_ManualOverlay','V') IS NOT NULL DROP VIEW Reporting.vw_Console_ManualOverlay;
GO
CREATE VIEW Reporting.vw_Console_ManualOverlay AS
    SELECT b.ProjectID, b.POShipDate, b.CustAgreedShipDate, b.MaterialBudget, b.LabourBudgetHours,
           b.PMHours, b.MechanicalHours, b.ElectricalHours, b.HydraulicHours, b.ManufacturingHours, b.OtherHours,
           p.PlannedShipDate, p.PercentComplete, p.LabourRunout, p.MaterialRunout,
           p.MaterialActual, p.TotalLineItems,
           p.LLTPOrdered, p.LLTPReleasedLate, p.LLTPOrderedLate, p.LLTPDeliveredLate,
           p.PartsReleasedLate, p.PartsOrderedLate, p.Delta1WkPercentDone, p.Delta1WkMaterial, p.ReRank
    FROM Reporting.vw_Console_BudgetCurrent b
    LEFT JOIN Reporting.vw_Console_PMEntryLatest p ON p.ProjectID = b.ProjectID;
GO
PRINT 'Macrodyne_Reporting_Staging: tables + views created.';
GO

------------------------------------------------------------------------------
-- 6. OPTIONAL — seed staging from prod (same server). Copies reference + budgets so
--    testers start from real data. Comment out if you want an empty staging DB.
------------------------------------------------------------------------------
-- IF DB_ID('Macrodyne_Reporting') IS NOT NULL
-- BEGIN
--     TRUNCATE TABLE Reporting.tblProjectBudgetDetail;
--     DELETE FROM Reporting.tblProjectBudget;
--     DELETE FROM Reporting.tblProjectPMEntry;
--     DELETE FROM Reporting.tlkpDisciplineCrosswalk;
--
--     INSERT INTO Reporting.tlkpDisciplineCrosswalk (HourDescription, Discipline, UpdatedAt)
--         SELECT HourDescription, Discipline, UpdatedAt FROM Macrodyne_Reporting.Reporting.tlkpDisciplineCrosswalk;
--
--     SET IDENTITY_INSERT Reporting.tblProjectBudget ON;
--     INSERT INTO Reporting.tblProjectBudget
--         (BudgetVersionID,ProjectID,EffectiveFrom,EffectiveTo,IsCurrent,Source,POShipDate,
--          CustAgreedShipDate,LatePenalty,MaterialBudget,LabourBudgetHours,PMHours,MechanicalHours,
--          ElectricalHours,HydraulicHours,ManufacturingHours,OtherHours,CreatedAt,CreatedBy)
--         SELECT BudgetVersionID,ProjectID,EffectiveFrom,EffectiveTo,IsCurrent,Source,POShipDate,
--          CustAgreedShipDate,LatePenalty,MaterialBudget,LabourBudgetHours,PMHours,MechanicalHours,
--          ElectricalHours,HydraulicHours,ManufacturingHours,OtherHours,CreatedAt,CreatedBy
--         FROM Macrodyne_Reporting.Reporting.tblProjectBudget;
--     SET IDENTITY_INSERT Reporting.tblProjectBudget OFF;
--
--     INSERT INTO Reporting.tblProjectBudgetDetail (BudgetVersionID,HourDescription,BudgetHours)
--         SELECT BudgetVersionID,HourDescription,BudgetHours
--         FROM Macrodyne_Reporting.Reporting.tblProjectBudgetDetail;
--
--     PRINT 'Staging seeded from Macrodyne_Reporting.';
-- END
-- GO

------------------------------------------------------------------------------
-- 7. Grant the console login on staging (Console-only; no vendor-DB access).
--    Replace <MacrodyneReportSvc> with your console login.
------------------------------------------------------------------------------
-- USE Macrodyne_Reporting_Staging;
-- CREATE USER [<MacrodyneReportSvc>] FOR LOGIN [<MacrodyneReportSvc>];
-- ALTER ROLE db_datareader ADD MEMBER [<MacrodyneReportSvc>];
-- ALTER ROLE db_datawriter ADD MEMBER [<MacrodyneReportSvc>];
-- GO
