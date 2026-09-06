/*==============================================================================
  014_machine_progress.sql  —  Project Console: per-MACHINE % complete

  The sibling of 011_discipline_progress.sql. Captures percent complete declared
  PER MACHINE (SpecID) per project per week, so the PM can square the efficacy of
  hours consumed vs budgeted for every budgeted unit — not just each discipline
  but each machine too. Earned hours (= %complete × budget) and CPI (earned ÷
  actual) are then CALCULATED per machine, exactly as they are per discipline.

  Grain: (ProjectID, YearWeekKey, SpecID). Upserted weekly like
  tblProjectDisciplineProgress / tblProjectPMEntry, so history accrues and the
  Budgets view reads the latest week per project+machine.

  SpecID is the ETO machine/spec number (the same key tblSpecHours / vwTimecards
  carry). Overhead/contingency specs (>= 700) are not machines and are not
  captured here.

  Idempotent. Run against the Console store (Macrodyne_Reporting / _Staging), NOT
  ETO. ETO stays vendor-owned and read-only.
==============================================================================*/

IF OBJECT_ID('Reporting.tblProjectMachineProgress', 'U') IS NULL
CREATE TABLE Reporting.tblProjectMachineProgress (
    ProgressID       INT IDENTITY(1,1) PRIMARY KEY,
    ProjectID        INT            NOT NULL,
    FiscalYear       INT            NULL,
    WeekNo           INT            NULL,
    YearWeekKey      INT            NOT NULL,   -- year*100 + WEEKNUM (matches tblProjectPMEntry)
    SpecID           INT            NOT NULL,   -- ETO machine/spec number (tblSpecHours.SpecID)
    PercentComplete  DECIMAL(5,4)   NULL,       -- 0..1 (declared by PM)
    EnteredBy        NVARCHAR(120)  NULL,
    CapturedAt       DATETIME       NOT NULL DEFAULT GETDATE()
);
GO

-- One row per project+week+machine; the app upserts on this key.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_MachineProgress_Key')
CREATE UNIQUE INDEX UX_MachineProgress_Key
    ON Reporting.tblProjectMachineProgress (ProjectID, YearWeekKey, SpecID);
GO

-- Fast "latest week per project+machine" read for the Budgets view.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_MachineProgress_Latest')
CREATE INDEX IX_MachineProgress_Latest
    ON Reporting.tblProjectMachineProgress (ProjectID, SpecID, YearWeekKey DESC)
    INCLUDE (PercentComplete);
GO
