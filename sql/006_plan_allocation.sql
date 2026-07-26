/*==============================================================================
  006_plan_allocation.sql  —  Project Console: Allocation metrics table (READY)

  Stands up the data model for the ACTIVITY ALLOCATION plan — the next phase after
  the simple schedule form (plan.py). Not yet wired to any UI; created now so the
  design is settled and history can start when the UI lands.

  The idea (owner, 2026-07-26): the budget is a pool of hours per discipline; the
  PLAN allocates those hours to ACTIVITIES (units of work). Each activity has a
  discipline, allocated hours, optional priority and dependencies, an allocatee, and
  a WEIGHT toward the project's % Done. The weight is a negotiated judgement (PM +
  discipline manager + allocatee), NOT necessarily equal or purely hours-based — so
  it is an explicit, editable field with a default and a record of who set it.

  OBJECTIVE % DONE (why this matters): once work is allocated, progress can be
  MEASURED, not guessed — actual hours from ETO (by discipline / spec) against the
  hours ALLOCATED to an activity give a real % complete. That replaces the PM's
  subjective % with an objective one. The columns below support both: a stored
  PercentComplete (manual for now) and the hooks (Discipline, SpecID, AllocatedHours)
  to compute the objective figure later.

  Idempotent. Run against the Console store (Macrodyne_Reporting), NOT ETO.
  ETO stays vendor-owned and read-only.
==============================================================================*/

IF OBJECT_ID('Reporting.tblProjectPlanAllocation', 'U') IS NULL
CREATE TABLE Reporting.tblProjectPlanAllocation (
    AllocationID     INT IDENTITY(1,1) PRIMARY KEY,
    ProjectID        INT            NOT NULL,
    ActivityName     NVARCHAR(200)  NOT NULL,
    Discipline       NVARCHAR(40)   NULL,   -- one of the 6 disciplines (ties to the crosswalk)
    SpecID           FLOAT          NULL,   -- optional ETO spec/machine link (for objective %)
    AllocatedHours   DECIMAL(12,2)  NULL,   -- budgeted hours allocated to this activity
    Priority         INT            NULL,   -- lower = higher priority (PM's ordering)
    DependsOn        NVARCHAR(400)  NULL,   -- predecessor AllocationIDs, comma-separated (simple for now)
    Allocatee        NVARCHAR(120)  NULL,   -- person doing the work
    -- weightage: the negotiated contribution of this activity to project % Done.
    -- NULL => fall back to AllocatedHours share at rollup time.
    Weight           DECIMAL(9,4)   NULL,
    WeightSetBy      NVARCHAR(120)  NULL,   -- who agreed the weight (audit of the judgement)
    WeightSetAt      DATETIME       NULL,
    -- progress: manual today; the objective figure (ETO actual hrs / AllocatedHours) lands later.
    PercentComplete  DECIMAL(5,4)   NULL,   -- 0..1
    PlannedStart     DATE           NULL,
    PlannedFinish    DATE           NULL,
    IsActive         BIT            NOT NULL DEFAULT 1,
    CreatedAt        DATETIME       NOT NULL DEFAULT GETDATE(),
    CreatedBy        NVARCHAR(120)  NULL,
    UpdatedAt        DATETIME       NULL,
    UpdatedBy        NVARCHAR(120)  NULL
);
GO

-- Fast lookup of a project's active activities.
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'IX_PlanAllocation_Project')
CREATE INDEX IX_PlanAllocation_Project
    ON Reporting.tblProjectPlanAllocation (ProjectID) WHERE IsActive = 1;
GO

/*------------------------------------------------------------------------------
  Rollup view — weighted % Done per project from the allocation.
  Weight defaults to the activity's share of allocated hours when not set.
  This is the DERIVED % Done that will replace the manual PM figure once the
  allocation UI is populated. (ETO actuals are joined in Python, not here — the
  Console store has no cross-DB link to ETO, by design.)
------------------------------------------------------------------------------*/
IF OBJECT_ID('Reporting.vw_Console_PlanRollup', 'V') IS NOT NULL
    DROP VIEW Reporting.vw_Console_PlanRollup;
GO
CREATE VIEW Reporting.vw_Console_PlanRollup AS
    SELECT
        ProjectID,
        COUNT(*)                                   AS Activities,
        SUM(ISNULL(AllocatedHours, 0))             AS AllocatedHours,
        -- weighted % done: Σ(w · pct) / Σ(w), w = Weight else AllocatedHours else 1
        CASE WHEN SUM(CASE WHEN Weight IS NOT NULL THEN Weight
                           WHEN AllocatedHours IS NOT NULL THEN AllocatedHours
                           ELSE 1 END) = 0 THEN NULL
             ELSE SUM(CASE WHEN Weight IS NOT NULL THEN Weight
                           WHEN AllocatedHours IS NOT NULL THEN AllocatedHours
                           ELSE 1 END * ISNULL(PercentComplete, 0))
                / SUM(CASE WHEN Weight IS NOT NULL THEN Weight
                           WHEN AllocatedHours IS NOT NULL THEN AllocatedHours
                           ELSE 1 END)
        END                                        AS PercentDoneWeighted
    FROM Reporting.tblProjectPlanAllocation
    WHERE IsActive = 1
    GROUP BY ProjectID;
GO
