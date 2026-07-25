-- ============================================================================
-- 001_create_macrodyne_reporting.sql
-- Project Console Reporting store — budgets + PM entries (system of record for the
-- manual half of the Project Console dashboards), per CARPEDIA_DB_SCHEMA_DESIGN.md.
--
-- Separate IT-owned database on MACRO-ETO-SVR\SQLEXPRESS, isolated from the
-- vendor's Macrodyne_Production. Run as sysadmin. Idempotent-ish (guards on create).
-- Owner: Vijay Nair (IT) · 2026-07-25
-- ============================================================================

------------------------------------------------------------------------------
-- 0. Database + schema
------------------------------------------------------------------------------
IF DB_ID('Macrodyne_Reporting') IS NULL
    CREATE DATABASE Macrodyne_Reporting;
GO
USE Macrodyne_Reporting;
GO
IF SCHEMA_ID('Reporting') IS NULL
    EXEC('CREATE SCHEMA Reporting');
GO

------------------------------------------------------------------------------
-- 1. Discipline crosswalk (single source of truth: HourDescription -> discipline)
--    Seeded by carpedia_sync from the Budgets tab grouping. BOTH the budget
--    roll-up and the ETO actual-hours re-code read this, so they can't drift.
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.tlkpDisciplineCrosswalk','U') IS NULL
CREATE TABLE Reporting.tlkpDisciplineCrosswalk (
    HourDescription   NVARCHAR(80)  NOT NULL PRIMARY KEY,
    Discipline        NVARCHAR(40)  NOT NULL,
    UpdatedAt         DATETIME      NOT NULL DEFAULT GETDATE()
);
GO

------------------------------------------------------------------------------
-- 2. Budget header — versioned (SCD-2). One row per project per version.
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
-- one current version per project
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name='UX_ProjectBudget_Current')
CREATE UNIQUE INDEX UX_ProjectBudget_Current
    ON Reporting.tblProjectBudget(ProjectID) WHERE IsCurrent = 1;
GO

------------------------------------------------------------------------------
-- 3. Budget detail — fine-grain hours by HourDescription per version
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
-- 4. PM entries — weekly time series (versioned by (ProjectID, YearWeekKey))
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.tblProjectPMEntry','U') IS NULL
CREATE TABLE Reporting.tblProjectPMEntry (
    PMEntryID           INT IDENTITY(1,1) PRIMARY KEY,
    ProjectID           INT           NOT NULL,
    FiscalYear          INT           NULL,
    WeekNo              INT           NULL,
    YearWeekKey         INT           NOT NULL,
    PlannedShipDate     DATE          NULL,   -- 2099 placeholder normalised to NULL on load
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
-- 5. Views — the stable interface the dashboard reads
------------------------------------------------------------------------------
IF OBJECT_ID('Reporting.vw_Console_BudgetCurrent','V') IS NOT NULL
    DROP VIEW Reporting.vw_Console_BudgetCurrent;
GO
CREATE VIEW Reporting.vw_Console_BudgetCurrent AS
    SELECT * FROM Reporting.tblProjectBudget WHERE IsCurrent = 1;
GO

IF OBJECT_ID('Reporting.vw_Console_PMEntryLatest','V') IS NOT NULL
    DROP VIEW Reporting.vw_Console_PMEntryLatest;
GO
CREATE VIEW Reporting.vw_Console_PMEntryLatest AS
    SELECT p.*
    FROM Reporting.tblProjectPMEntry p
    JOIN (SELECT ProjectID, MAX(YearWeekKey) AS mx
          FROM Reporting.tblProjectPMEntry
          WHERE IncludeFlag = 1
          GROUP BY ProjectID) m
      ON p.ProjectID = m.ProjectID AND p.YearWeekKey = m.mx;
GO

-- NOTE: actual labour hours per project × discipline is computed in PYTHON
-- (console_engine reads ETO live over the read-only ETO connection and applies the
-- crosswalk loaded from Reporting.tlkpDisciplineCrosswalk). This DB has NO link to
-- the vendor database — Python is the only bridge. Nothing here reads Macrodyne_Production.

-- Manual overlay = current budget + latest PM entry, one row per project.
-- The dashboard reads this (manual side); ETO actuals are joined in the Python engine.
IF OBJECT_ID('Reporting.vw_Console_ManualOverlay','V') IS NOT NULL
    DROP VIEW Reporting.vw_Console_ManualOverlay;
GO
CREATE VIEW Reporting.vw_Console_ManualOverlay AS
    SELECT b.ProjectID,
           b.POShipDate, b.CustAgreedShipDate,
           b.MaterialBudget, b.LabourBudgetHours,
           b.PMHours, b.MechanicalHours, b.ElectricalHours,
           b.HydraulicHours, b.ManufacturingHours, b.OtherHours,
           p.PlannedShipDate, p.PercentComplete, p.LabourRunout, p.MaterialRunout,
           p.MaterialActual, p.TotalLineItems,
           p.LLTPOrdered, p.LLTPReleasedLate, p.LLTPOrderedLate, p.LLTPDeliveredLate,
           p.PartsReleasedLate, p.PartsOrderedLate,
           p.Delta1WkPercentDone, p.Delta1WkMaterial, p.ReRank
    FROM Reporting.vw_Console_BudgetCurrent b
    LEFT JOIN Reporting.vw_Console_PMEntryLatest p ON p.ProjectID = b.ProjectID;
GO

PRINT 'Macrodyne_Reporting: tables + views created.';
GO

-- ============================================================================
-- 6. Ownership & login  (run as a MACRODYNE-controlled sysadmin — NOT the vendor)
-- ============================================================================
-- OWNERSHIP — this database, its schemas, and everything in them are Macrodyne IP.
-- The ETO vendor account (totaletoadmin) must NOT own or control them. Set the
-- owner to a Macrodyne-controlled principal (a Macrodyne IT service login, or an
-- account only Macrodyne administers). Replace <MacrodyneReportingOwner> below.
-- ALTER AUTHORIZATION ON DATABASE::Macrodyne_Reporting TO [<MacrodyneReportingOwner>];
-- ALTER AUTHORIZATION ON SCHEMA::Reporting              TO [<MacrodyneReportingOwner>];
-- GO
--
-- The Console login needs NO access to the vendor DB — Python reads ETO over a
-- SEPARATE read-only connection (the existing ETO login). This login is Console-only.
--
-- CONNECTION LOGIN for console_sync — a MACRODYNE-controlled login with WRITE on
-- Macrodyne_Reporting (here) and nothing else. It needs NO access to the vendor DB.
-- USE Macrodyne_Reporting;
-- CREATE USER [<MacrodyneReportSvc>] FOR LOGIN [<MacrodyneReportSvc>];
-- ALTER ROLE db_datareader ADD MEMBER [<MacrodyneReportSvc>];
-- ALTER ROLE db_datawriter ADD MEMBER [<MacrodyneReportSvc>];   -- write here only
-- GO
-- Python reads ETO over a separate read-only ETO connection (the existing
-- TotalETOReportWriter login). Set MACRODYNE_REPORTING_USER/PWD to the Console login;
-- the ETO connection uses its own creds (ETO read-only).
