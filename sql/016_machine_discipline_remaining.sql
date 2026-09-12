/*==============================================================================
  016_machine_discipline_remaining.sql  —  Project Console: capture progress as
  HOURS REMAINING TO COMPLETION at the machine × discipline cell.

  The Plan page now asks the PM for hours remaining to completion per cell instead
  of a % complete. % complete is DERIVED from it:
        % complete = actual / (actual + remaining)        (EAC = actual + remaining)
  and the derived % is still written to PercentComplete on the same row, so the
  Budgets page and the dashboard/scorecard run-out keep reading it unchanged.

  This migration just adds the RemainingHours column to the existing
  Reporting.tblProjectMachineDisciplineProgress table (015). Existing rows keep
  their PercentComplete; RemainingHours is NULL until the PM saves the plan again
  under the new form.

  Idempotent. Run against the Console store (Macrodyne_Reporting / _Staging), NOT
  ETO. ETO stays vendor-owned and read-only.
==============================================================================*/

IF COL_LENGTH('Reporting.tblProjectMachineDisciplineProgress', 'RemainingHours') IS NULL
    ALTER TABLE Reporting.tblProjectMachineDisciplineProgress
        ADD RemainingHours DECIMAL(12,2) NULL;   -- PM-entered hours remaining to completion (>= 0)
GO
