/*==============================================================================
  015_machine_discipline_progress.sql  —  Project Console: % complete at the
  MACHINE × DISCIPLINE grain (the finest budgeted unit).

  SUPERSEDES 014_machine_progress.sql. The plan now captures percent complete for
  each machine × discipline CELL — the same grid the Budgets page shows budget vs
  actual on — so hours consumed can be squared against hours budgeted at the
  finest grain, and earned hours (= %×budget) and CPI (earned÷actual) are
  calculated per cell. The per-discipline % the dashboard/scorecard run-out reads
  (tblProjectDisciplineProgress) is now DERIVED from these cells (budget-weighted)
  and written on save — the PM enters progress once, at the cell.

  If 014 was already run, its table (tblProjectMachineProgress) is simply unused;
  it can be left in place or dropped. This migration does not touch it.

  Grain: (ProjectID, YearWeekKey, SpecID, Discipline). SpecID is the ETO machine/
  spec number; the aggregated Overhead / Contingency group (specs >= 700) is stored
  under the sentinel SpecID = 0 so every budgeted hour (machines + overhead) has a
  cell and the discipline roll-up is complete. Upserted weekly like the sibling
  progress tables.

  Idempotent. Run against the Console store (Macrodyne_Reporting / _Staging), NOT
  ETO. ETO stays vendor-owned and read-only.
==============================================================================*/

IF OBJECT_ID('Reporting.tblProjectMachineDisciplineProgress', 'U') IS NULL
CREATE TABLE Reporting.tblProjectMachineDisciplineProgress (
    ProgressID       INT IDENTITY(1,1) PRIMARY KEY,
    ProjectID        INT            NOT NULL,
    FiscalYear       INT            NULL,
    WeekNo           INT            NULL,
    YearWeekKey      INT            NOT NULL,   -- year*100 + WEEKNUM (matches tblProjectPMEntry)
    SpecID           INT            NOT NULL,   -- ETO machine/spec number; 0 = Overhead/Contingency group
    Discipline       NVARCHAR(40)   NOT NULL,   -- one of the 6 disciplines (ties to the crosswalk)
    PercentComplete  DECIMAL(5,4)   NULL,       -- 0..1 (declared by PM at the machine×discipline cell)
    EnteredBy        NVARCHAR(120)  NULL,
    CapturedAt       DATETIME       NOT NULL DEFAULT GETDATE()
);
GO

-- One row per project+week+machine+discipline; the app upserts on this key.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_MachineDisciplineProgress_Key')
CREATE UNIQUE INDEX UX_MachineDisciplineProgress_Key
    ON Reporting.tblProjectMachineDisciplineProgress (ProjectID, YearWeekKey, SpecID, Discipline);
GO

-- Fast "latest week per project+machine+discipline" read for the Plan / Budgets views.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_MachineDisciplineProgress_Latest')
CREATE INDEX IX_MachineDisciplineProgress_Latest
    ON Reporting.tblProjectMachineDisciplineProgress (ProjectID, SpecID, Discipline, YearWeekKey DESC)
    INCLUDE (PercentComplete);
GO
