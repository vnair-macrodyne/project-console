-- ============================================================================
-- 004_create_store_login.sql
-- Dedicated, MACRODYNE-OWNED SQL login for the Project Console store.
--
-- This is the identity the web app uses to READ/WRITE the Reporting store
-- (budgets, PM entries, console users). It is deliberately NOT the vendor
-- account 'TotalETOReportWriter' — that login stays confined to the read-only
-- ETO connection and is never granted anything here.
--
-- Scope of rights: datareader + datawriter on the Reporting store ONLY.
--   • No access to the vendor database (Macrodyne_Production).
--   • No sysadmin / no DDL — the install scripts (001/003) own the schema.
--
-- Run as a Macrodyne sysadmin. Idempotent-ish (guards on create).
--
--   >>> BEFORE RUNNING: replace the password placeholder below. <<<
--   Do NOT commit the real password anywhere. It goes only into the app's
--   .env as CONSOLE_STORE_PWD (which is gitignored).
-- ============================================================================

------------------------------------------------------------------------------
-- 0. Server-level login (SQL auth). Lives in master.
------------------------------------------------------------------------------
USE master;
GO
IF SUSER_ID('MacrodyneConsoleSvc') IS NULL
    CREATE LOGIN [MacrodyneConsoleSvc]
        WITH PASSWORD = 'CHANGE_ME_StrongP@ssw0rd!',   -- <<< replace before running
             CHECK_POLICY = ON,
             DEFAULT_DATABASE = [Macrodyne_Reporting_Staging];
GO

------------------------------------------------------------------------------
-- 1. Grant on STAGING  (Macrodyne_Reporting_Staging)  — reader + writer
------------------------------------------------------------------------------
USE Macrodyne_Reporting_Staging;
GO
IF USER_ID('MacrodyneConsoleSvc') IS NULL
    CREATE USER [MacrodyneConsoleSvc] FOR LOGIN [MacrodyneConsoleSvc];
GO
ALTER ROLE db_datareader ADD MEMBER [MacrodyneConsoleSvc];
ALTER ROLE db_datawriter ADD MEMBER [MacrodyneConsoleSvc];
GO
PRINT 'MacrodyneConsoleSvc granted reader+writer on Macrodyne_Reporting_Staging.';
GO

------------------------------------------------------------------------------
-- 2. OPTIONAL — same grant on PROD (Macrodyne_Reporting) when you go live.
--    Uncomment when ready. The SAME login serves both; the app picks the DB
--    via CONSOLE_ENV / CONSOLE_STORE_DB, no code or login change needed.
------------------------------------------------------------------------------
-- USE Macrodyne_Reporting;
-- GO
-- IF USER_ID('MacrodyneConsoleSvc') IS NULL
--     CREATE USER [MacrodyneConsoleSvc] FOR LOGIN [MacrodyneConsoleSvc];
-- GO
-- ALTER ROLE db_datareader ADD MEMBER [MacrodyneConsoleSvc];
-- ALTER ROLE db_datawriter ADD MEMBER [MacrodyneConsoleSvc];
-- GO
-- PRINT 'MacrodyneConsoleSvc granted reader+writer on Macrodyne_Reporting.';
-- GO

------------------------------------------------------------------------------
-- 3. Sanity check — confirm the login can see the store tables.
------------------------------------------------------------------------------
-- EXECUTE AS LOGIN = 'MacrodyneConsoleSvc';
--     SELECT COUNT(*) AS BudgetRows FROM Macrodyne_Reporting_Staging.Reporting.tblProjectBudget;
-- REVERT;
-- GO
