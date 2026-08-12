/*==============================================================================
  011_discipline_progress.sql  —  Project Console: per-discipline % complete

  Captures the ONE judgement the run-out engine needs: percent complete, entered
  PER DISCIPLINE per project per week (replacing the single project-level % Done).
  Everything downstream — labour run-out (EAC = actual ÷ %complete), the project
  %C roll-up, earned value / CPI — is then CALCULATED, not typed. This is the
  Carpedia model: progress is declared per discipline; the forecast is derived.

  Grain: (ProjectID, YearWeekKey, Discipline). Upserted weekly like tblProjectPMEntry,
  so history accrues and the dashboard reads the latest week per project+discipline.

  Idempotent. Run against the Console store (Macrodyne_Reporting / _Staging), NOT ETO.
  ETO stays vendor-owned and read-only.
==============================================================================*/

IF OBJECT_ID('Reporting.tblProjectDisciplineProgress', 'U') IS NULL
CREATE TABLE Reporting.tblProjectDisciplineProgress (
    ProgressID       INT IDENTITY(1,1) PRIMARY KEY,
    ProjectID        INT            NOT NULL,
    FiscalYear       INT            NULL,
    WeekNo           INT            NULL,
    YearWeekKey      INT            NOT NULL,   -- year*100 + WEEKNUM (matches tblProjectPMEntry)
    Discipline       NVARCHAR(40)   NOT NULL,   -- one of the 6 disciplines (ties to the crosswalk)
    PercentComplete  DECIMAL(5,4)   NULL,       -- 0..1 (declared by PM / discipline lead)
    EnteredBy        NVARCHAR(120)  NULL,
    CapturedAt       DATETIME       NOT NULL DEFAULT GETDATE()
);
GO

-- One row per project+week+discipline; the app upserts on this key.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'UX_DisciplineProgress_Key')
CREATE UNIQUE INDEX UX_DisciplineProgress_Key
    ON Reporting.tblProjectDisciplineProgress (ProjectID, YearWeekKey, Discipline);
GO

-- Fast "latest week per project+discipline" read for the dashboard.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_DisciplineProgress_Latest')
CREATE INDEX IX_DisciplineProgress_Latest
    ON Reporting.tblProjectDisciplineProgress (ProjectID, Discipline, YearWeekKey DESC)
    INCLUDE (PercentComplete);
GO
