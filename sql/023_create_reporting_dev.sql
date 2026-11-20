-- ============================================================================
-- 023_create_reporting_dev.sql
-- DEV copy of the Project Console Reporting store: a throwaway database that
-- every new build is tried against before it goes to staging.
--
--   source : Macrodyne_Reporting_Staging   (read only; COPY_ONLY backup, so the
--                                            staging backup chain is untouched)
--   dest   : Macrodyne_Reporting_Dev       (created, or OVERWRITTEN on re-run)
--   server : MACRO-ETO-SVR\SQLEXPRESS (same server as staging, prod and ETO)
--
-- Why restore instead of 003 + migrations: the copy carries the full schema
-- through the latest migration (022) and realistic data in one step. Re-run it
-- whenever dev needs a fresh copy.
--
-- ETO (Macrodyne_Production) is not referenced; dev reads it read-only like
-- every other environment.
--
-- Run as a MACRODYNE-controlled sysadmin. Owner: Vijay Nair (IT).
-- ============================================================================
SET NOCOUNT ON;
USE master;
GO

IF DB_ID('Macrodyne_Reporting_Staging') IS NULL
    THROW 50023, 'Macrodyne_Reporting_Staging not found on this server.', 1;
GO

------------------------------------------------------------------------------
-- 1. Copy-only backup of staging to the instance's default backup folder
------------------------------------------------------------------------------
DECLARE @bak NVARCHAR(400) =
    CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS NVARCHAR(300))
    + N'\Macrodyne_Reporting_Staging_for_dev.bak';

BACKUP DATABASE Macrodyne_Reporting_Staging
    TO DISK = @bak
    WITH COPY_ONLY, INIT, FORMAT, NAME = N'Staging copy for Dev';

------------------------------------------------------------------------------
-- 2. Restore as Macrodyne_Reporting_Dev with its own file names
------------------------------------------------------------------------------
DECLARE @data NVARCHAR(300) = CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS NVARCHAR(300));
DECLARE @log  NVARCHAR(300) = CAST(SERVERPROPERTY('InstanceDefaultLogPath')  AS NVARCHAR(300));
DECLARE @dataName SYSNAME, @logName SYSNAME;

SELECT @dataName = name FROM Macrodyne_Reporting_Staging.sys.database_files WHERE type_desc = 'ROWS';
SELECT @logName  = name FROM Macrodyne_Reporting_Staging.sys.database_files WHERE type_desc = 'LOG';

IF DB_ID('Macrodyne_Reporting_Dev') IS NOT NULL
    ALTER DATABASE Macrodyne_Reporting_Dev SET SINGLE_USER WITH ROLLBACK IMMEDIATE;

DECLARE @moveData NVARCHAR(400) = @data + N'Macrodyne_Reporting_Dev.mdf';
DECLARE @moveLog  NVARCHAR(400) = @log  + N'Macrodyne_Reporting_Dev_log.ldf';

RESTORE DATABASE Macrodyne_Reporting_Dev
    FROM DISK = @bak
    WITH REPLACE,
         MOVE @dataName TO @moveData,
         MOVE @logName  TO @moveLog;

ALTER DATABASE Macrodyne_Reporting_Dev SET MULTI_USER;
ALTER DATABASE Macrodyne_Reporting_Dev SET RECOVERY SIMPLE;
GO

------------------------------------------------------------------------------
-- 3. Dev's own login. The restore brings staging's database users across;
--    remove them so the staging login cannot open dev, then map the dev login
--    with the same rights the app has on staging.
--    Create the login first (password kept in the dev Key Vault, not here):
--      CREATE LOGIN [MacrodyneConsoleSvcDev] WITH PASSWORD = '<from vault>',
--             DEFAULT_DATABASE = Macrodyne_Reporting_Dev, CHECK_POLICY = ON;
------------------------------------------------------------------------------
USE Macrodyne_Reporting_Dev;
GO
-- List the users the restore carried over; drop the staging app user by name:
SELECT name, type_desc FROM sys.database_principals
WHERE type IN ('S','U','G') AND principal_id > 4;
-- DROP USER [<staging app user>];

-- CREATE USER [MacrodyneConsoleSvcDev] FOR LOGIN [MacrodyneConsoleSvcDev];
-- ALTER ROLE db_datareader ADD MEMBER [MacrodyneConsoleSvcDev];
-- ALTER ROLE db_datawriter ADD MEMBER [MacrodyneConsoleSvcDev];
-- (plus any object grants staging's app user holds; e.g. the 022 grants:)
-- GRANT SELECT, INSERT, UPDATE, DELETE ON Reporting.tblActiveProject     TO [MacrodyneConsoleSvcDev];
-- GRANT SELECT, INSERT                 ON Reporting.tblTrackedProjectLog TO [MacrodyneConsoleSvcDev];
GO
