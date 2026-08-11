-- sql/009_rework_threshold.sql — per-project Rework / NCR threshold on the PM entry.
-- Stored as a FRACTION (0.01 = 1%). NULL → the dashboard applies the 1% default.
-- Idempotent: safe to run more than once. Customer-owned Reporting store only (ETO untouched).
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = 'Reporting' AND TABLE_NAME = 'tblProjectPMEntry'
      AND COLUMN_NAME = 'ReworkThreshold')
BEGIN
    ALTER TABLE Reporting.tblProjectPMEntry ADD ReworkThreshold decimal(9,4) NULL;
END
GO
