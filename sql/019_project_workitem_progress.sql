/*==============================================================================
  019_project_workitem_progress.sql — plan progress at the WORK ITEM (HourType) grain

  Decision (Vijay, 2026-09-23, from the PMs): the Plan grid should capture progress at the
  work-item level — every ETO estimate line a PM can attribute a budget to — not just the 6
  rolled-up disciplines. A "work item" is an ETO HourType (the controlled ~58-value key,
  labelled by tlkpHourTypes.HourDescription — e.g. "Electrical Programming", "Fabrication/Welding").

  This table is the NEW source of truth for PM-entered progress. The PM enters RemainingHours per
  (machine, work item); % complete is derived = actual / (actual + remaining) and stored alongside.
  The existing discipline and machine×discipline progress tables become DERIVED roll-ups (written by
  plan.py on save from these rows), so the dashboard / scorecard / run-out read unchanged.

  Grain: ProjectID × YearWeekKey (week) × SpecID (machine; overhead specs ≥700 fold to SpecID 0)
         × HourType (work item). Budget/actual for the item come from ETO live (tblSpecHours /
         vwTimecards) — NOT stored here; only the PM's remaining + derived % live in the store.

  Idempotent. Run against the Console store (Macrodyne_Reporting), staging then prod, BEFORE deploying
  the matching console_web/plan.py. ETO stays vendor-owned and read-only.
==============================================================================*/

IF OBJECT_ID('Reporting.tblProjectWorkItemProgress', 'U') IS NULL
CREATE TABLE Reporting.tblProjectWorkItemProgress (
    ProgressID      INT           IDENTITY(1,1)
                    CONSTRAINT PK_tblProjectWorkItemProgress PRIMARY KEY,
    ProjectID       INT           NOT NULL,
    FiscalYear      INT           NOT NULL,
    WeekNo          INT           NOT NULL,
    YearWeekKey     INT           NOT NULL,     -- e.g. 202639 (matches the other progress tables)
    SpecID          INT           NOT NULL,     -- machine; 0 = Overhead / Contingency group (specs >= 700)
    HourType        INT           NOT NULL,     -- the work item (ETO tlkpHourTypes.HourType)
    RemainingHours  DECIMAL(12,2) NULL,         -- PM input: hours remaining to completion for this item
    PercentComplete DECIMAL(9,4)  NULL,         -- derived = actual / (actual + remaining), 0..1
    EnteredBy       NVARCHAR(120) NULL,
    CapturedAt      DATETIME      NOT NULL
                    CONSTRAINT DF_tblProjectWorkItemProgress_CapturedAt DEFAULT (GETDATE())
);
GO

-- one row per (project, week, machine, work item)
IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = 'UX_tblProjectWorkItemProgress_cell'
                 AND object_id = OBJECT_ID('Reporting.tblProjectWorkItemProgress'))
    CREATE UNIQUE INDEX UX_tblProjectWorkItemProgress_cell
        ON Reporting.tblProjectWorkItemProgress (ProjectID, YearWeekKey, SpecID, HourType);
GO
