-- ============================================================================
-- 008_hourtype_discipline.sql
-- The AUTHORITATIVE HourType -> discipline crosswalk, anchored to ETO's own
-- HourDepartment. This replaces the incomplete HourDescription-keyed crosswalk for
-- BUDGET (tblSpecHours is free-text on HourDescription; HourType is the controlled
-- key) and is the single source of truth going forward.
--
-- Confirmed 2026-07-27: grouping tblSpecHours by HourType and mapping via the rule in
-- console/domain/hourtype_map.py reconciles EXACTLY to ETO's 3-bucket estimate
-- (Admin/Eng/Mfg) on every tested project (230219, 240033, 220154), with zero
-- free-text residue.
--
-- Seeded FROM ETO by console_sync (HourTypeDisciplineDAO.seed_from_eto) — never
-- hard-coded here, so it stays tenant-agnostic. Rows a human overrides get
-- Source='manual' and are preserved on re-seed. No vendor-DB objects; this lives in
-- the customer-owned Reporting store.
--
-- Run after 001. Owner: Vijay Nair (IT) · 2026-07-27
-- ============================================================================
USE Macrodyne_Reporting;
GO

IF OBJECT_ID('Reporting.tlkpHourTypeDiscipline', 'U') IS NULL
BEGIN
    CREATE TABLE Reporting.tlkpHourTypeDiscipline (
        HourType        INT           NOT NULL
                        CONSTRAINT PK_tlkpHourTypeDiscipline PRIMARY KEY,
        HourDescription NVARCHAR(80)  NULL,        -- ETO's controlled description (label)
        Discipline      NVARCHAR(40)  NOT NULL,    -- PM / Mechanical / Hydraulic / Electrical / Manufacturing / Other
        Source          NVARCHAR(20)  NOT NULL     -- 'ETO' (seeded) | 'manual' (human override, kept on re-seed)
                        CONSTRAINT DF_tlkpHourTypeDiscipline_Source DEFAULT ('ETO'),
        UpdatedAt       DATETIME      NOT NULL
                        CONSTRAINT DF_tlkpHourTypeDiscipline_UpdatedAt DEFAULT (GETDATE())
    );
    PRINT 'Created Reporting.tlkpHourTypeDiscipline (seed from ETO via console_sync).';
END
ELSE
    PRINT 'Reporting.tlkpHourTypeDiscipline already exists — skipped.';
GO
