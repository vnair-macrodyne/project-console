-- ============================================================================
-- 002_project_snapshot.sql
-- The HISTORY / TRAJECTORY layer — one row per project per week capturing the full
-- state (budget in effect + ETO actuals as-of-that-week + PM progress). This is the
-- training table for future prediction models (estimate-at-completion, overrun risk,
-- schedule slippage). Populated by console_sync (weekly) from ETO + the versioned
-- budget + the weekly PM entry.
--
-- No vendor-DB link here either — Python reads ETO and writes these rows.
-- Run after 001. Owner: Vijay Nair (IT) · 2026-07-25
-- ============================================================================
USE Macrodyne_Reporting;
GO

IF OBJECT_ID('Reporting.tblProjectWeeklySnapshot','U') IS NULL
CREATE TABLE Reporting.tblProjectWeeklySnapshot (
    SnapshotID          INT IDENTITY(1,1) PRIMARY KEY,
    ProjectID           INT           NOT NULL,
    YearWeekKey         INT           NOT NULL,   -- 202629 — the "as of" week
    SnapshotDate        DATE          NOT NULL,   -- week-end date the actuals are cut at
    -- budget in effect that week (points at the SCD-2 version) + denormalised totals
    BudgetVersionID     INT           NULL
        REFERENCES Reporting.tblProjectBudget(BudgetVersionID),
    LabourBudgetHours   DECIMAL(12,2) NULL,
    MaterialBudget      DECIMAL(14,2) NULL,
    -- ETO actuals cut at SnapshotDate (TimeDate <= week-end), by discipline
    ActualLabourHours   DECIMAL(12,2) NULL,
    ActualLabourCost    DECIMAL(14,2) NULL,
    PMActualHours       DECIMAL(12,2) NULL,
    MechanicalActualHours   DECIMAL(12,2) NULL,
    ElectricalActualHours   DECIMAL(12,2) NULL,
    HydraulicActualHours    DECIMAL(12,2) NULL,
    ManufacturingActualHours DECIMAL(12,2) NULL,
    OtherActualHours    DECIMAL(12,2) NULL,
    -- PM progress/material that week (from tblProjectPMEntry)
    PercentComplete     DECIMAL(6,4)  NULL,
    LabourRunout        DECIMAL(7,4)  NULL,
    MaterialRunout      DECIMAL(7,4)  NULL,
    MaterialActual      DECIMAL(14,2) NULL,
    -- derived, stored for convenient modelling (recomputable)
    PctLabourConsumedHrs AS (CASE WHEN LabourBudgetHours > 0
                             THEN ActualLabourHours / LabourBudgetHours END),
    CreatedAt           DATETIME      NOT NULL DEFAULT GETDATE(),
    CONSTRAINT UX_ProjectWeeklySnapshot UNIQUE (ProjectID, YearWeekKey)
);
GO

-- Trajectory view: a project's full weekly history, ordered — the shape a model trains on.
IF OBJECT_ID('Reporting.vw_Console_ProjectTrajectory','V') IS NOT NULL
    DROP VIEW Reporting.vw_Console_ProjectTrajectory;
GO
CREATE VIEW Reporting.vw_Console_ProjectTrajectory AS
    SELECT ProjectID, YearWeekKey, SnapshotDate,
           LabourBudgetHours, ActualLabourHours, PctLabourConsumedHrs,
           MaterialBudget, MaterialActual,
           PercentComplete, LabourRunout, MaterialRunout,
           PMActualHours, MechanicalActualHours, ElectricalActualHours,
           HydraulicActualHours, ManufacturingActualHours, OtherActualHours
    FROM Reporting.tblProjectWeeklySnapshot;
GO

PRINT 'Macrodyne_Reporting: weekly snapshot (history/trajectory) layer created.';
GO

-- POPULATION (console_sync, later): for each project × week, snapshot
--   • the budget version whose EffectiveFrom..EffectiveTo brackets the week,
--   • ETO actual hours/cost by discipline WHERE TimeDate <= week-end (from ETO, in Python),
--   • the PM entry for that week.
-- Because ETO timecards are dated, the full history can be BACKFILLED from ETO on first
-- run — every project's trajectory from week one, ready for modelling.
