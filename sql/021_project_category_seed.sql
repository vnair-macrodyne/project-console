-- 021_project_category_seed.sql
-- Project Types report (Project Management menu). The project type/category does NOT exist in
-- ETO (probe console_diag_project_type.py, 2026-10-29: all 8 tblProjects custom fields are empty
-- and there is no project-type lookup). The classification lives in Sextant and is SEEDED here
-- from the "ETO Projects" sheet (ETO_Project_Types_20260917.xlsx): 224 projects, 26 categories
-- rolled up to 7 Category Groups.
--
--   Reporting.tlkpProjectCategoryGroup  Category -> CategoryGroup (+ GroupSort)  -- reference taxonomy
--   Reporting.tblProjectCategory        ProjectID -> Category                    -- per-project tag
--
-- Consumers (queries.py): reports "project_types" (summary count/%) and "project_types_detail"
-- (per-project list). Both read defensively, so the app still runs if this hasn't been applied.
--
-- Idempotent. The taxonomy is UPSERTed (kept in sync). Per-project tags are INSERT-IF-ABSENT, so
-- later hand-curation / re-classification in the table is NOT overwritten on re-run.

IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
               WHERE s.name='Reporting' AND t.name='tlkpProjectCategoryGroup')
BEGIN
    CREATE TABLE Reporting.tlkpProjectCategoryGroup (
        Category      NVARCHAR(80)  NOT NULL PRIMARY KEY,
        CategoryGroup NVARCHAR(60)  NOT NULL,
        GroupSort     INT           NOT NULL CONSTRAINT DF_ProjCatGroup_Sort DEFAULT (99)
    );
END
GO

IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON s.schema_id=t.schema_id
               WHERE s.name='Reporting' AND t.name='tblProjectCategory')
BEGIN
    CREATE TABLE Reporting.tblProjectCategory (
        ProjectID   INT           NOT NULL PRIMARY KEY,
        Category    NVARCHAR(80)  NOT NULL,
        Source      NVARCHAR(60)  NOT NULL CONSTRAINT DF_ProjCat_Source  DEFAULT ('sheet-2026-09-17'),
        UpdatedDate DATETIME      NOT NULL CONSTRAINT DF_ProjCat_Updated DEFAULT (GETDATE())
    );
END
GO

-- Taxonomy (upsert): Category -> Group + sort
MERGE Reporting.tlkpProjectCategoryGroup AS tgt
USING (VALUES
        (N'Assembly Press', N'Core Press Types', 1),
        (N'Blanking Press', N'Core Press Types', 1),
        (N'Compression Molding (SMC)', N'Core Press Types', 1),
        (N'Draw / Deep Draw', N'Core Press Types', 1),
        (N'Extrusion', N'Core Press Types', 1),
        (N'Forging', N'Core Press Types', 1),
        (N'Hot Stamping / Heated Platen', N'Core Press Types', 1),
        (N'Hydroforming / SPF', N'Core Press Types', 1),
        (N'Metalforming', N'Core Press Types', 1),
        (N'Press', N'Core Press Types', 1),
        (N'Pulp Bailing Press', N'Core Press Types', 1),
        (N'Specialty Presses', N'Core Press Types', 1),
        (N'Stretch Forming', N'Core Press Types', 1),
        (N'Controls Retrofits', N'Retrofit / Upgrades', 2),
        (N'Mechanical Retrofits', N'Retrofit / Upgrades', 2),
        (N'Automation Systems', N'Systems', 3),
        (N'Press Lines / Cells', N'Systems', 3),
        (N'Auxiliary Systems', N'Subsystems', 4),
        (N'Material Handling', N'Subsystems', 4),
        (N'Thermal Systems', N'Subsystems', 4),
        (N'Engineering Studies', N'Engineering', 5),
        (N'Prototype / Testing', N'Engineering', 5),
        (N'R&D / Internal Projects', N'Engineering', 5),
        (N'Simulation & Process Dev', N'Engineering', 5),
        (N'Warranty Work', N'Aftermarket', 6),
        (N'Non-Standard / Other', N'Misc', 7)
    ) AS src (Category, CategoryGroup, GroupSort)
ON tgt.Category = src.Category
WHEN MATCHED THEN UPDATE SET tgt.CategoryGroup = src.CategoryGroup, tgt.GroupSort = src.GroupSort
WHEN NOT MATCHED THEN INSERT (Category, CategoryGroup, GroupSort)
     VALUES (src.Category, src.CategoryGroup, src.GroupSort);
GO

-- Per-project classification (insert if absent; existing rows / later curation left untouched)
INSERT INTO Reporting.tblProjectCategory (ProjectID, Category)
SELECT src.ProjectID, src.Category
FROM (VALUES
        (111163, N'Forging'),
        (121432, N'Press'),
        (141614, N'Metalforming'),
        (141615, N'Compression Molding (SMC)'),
        (161665, N'Metalforming'),
        (161672, N'Warranty Work'),
        (161674, N'Mechanical Retrofits'),
        (161679, N'Compression Molding (SMC)'),
        (161682, N'Press'),
        (161683, N'Press'),
        (161684, N'Press'),
        (161689, N'Hot Stamping / Heated Platen'),
        (171726, N'Compression Molding (SMC)'),
        (171731, N'Blanking Press'),
        (171732, N'Blanking Press'),
        (171738, N'Material Handling'),
        (171740, N'Press Lines / Cells'),
        (171744, N'Press'),
        (171745, N'Compression Molding (SMC)'),
        (171747, N'Metalforming'),
        (171766, N'Press'),
        (181772, N'Compression Molding (SMC)'),
        (181773, N'Compression Molding (SMC)'),
        (181775, N'Metalforming'),
        (181781, N'Material Handling'),
        (181782, N'Hot Stamping / Heated Platen'),
        (181784, N'Extrusion'),
        (181785, N'Auxiliary Systems'),
        (181788, N'Hot Stamping / Heated Platen'),
        (181789, N'Draw / Deep Draw'),
        (181794, N'Press'),
        (181795, N'Press'),
        (181797, N'Press'),
        (181803, N'Mechanical Retrofits'),
        (181810, N'Press'),
        (181811, N'Prototype / Testing'),
        (181812, N'Assembly Press'),
        (181814, N'Mechanical Retrofits'),
        (181820, N'Mechanical Retrofits'),
        (181821, N'Warranty Work'),
        (181843, N'Hot Stamping / Heated Platen'),
        (181844, N'Auxiliary Systems'),
        (181846, N'Press'),
        (181853, N'Mechanical Retrofits'),
        (181866, N'Press'),
        (181879, N'Mechanical Retrofits'),
        (181881, N'Compression Molding (SMC)'),
        (181884, N'Press'),
        (181906, N'Metalforming'),
        (191918, N'Compression Molding (SMC)'),
        (191920, N'Press'),
        (191925, N'Draw / Deep Draw'),
        (191926, N'Compression Molding (SMC)'),
        (191947, N'Hydroforming / SPF'),
        (191955, N'Metalforming'),
        (191956, N'Forging'),
        (191959, N'Mechanical Retrofits'),
        (192007, N'Press Lines / Cells'),
        (192009, N'Metalforming'),
        (192012, N'Draw / Deep Draw'),
        (192014, N'Press Lines / Cells'),
        (192020, N'Press'),
        (192033, N'Draw / Deep Draw'),
        (192038, N'Hydroforming / SPF'),
        (192051, N'Press'),
        (192053, N'Mechanical Retrofits'),
        (192057, N'Compression Molding (SMC)'),
        (192085, N'Press'),
        (192094, N'Hydroforming / SPF'),
        (192124, N'Compression Molding (SMC)'),
        (192133, N'Mechanical Retrofits'),
        (192137, N'Hydroforming / SPF'),
        (192142, N'Metalforming'),
        (192143, N'Hot Stamping / Heated Platen'),
        (192151, N'Mechanical Retrofits'),
        (192159, N'Draw / Deep Draw'),
        (202170, N'Press'),
        (202190, N'Mechanical Retrofits'),
        (202191, N'Prototype / Testing'),
        (202207, N'Press'),
        (202209, N'Mechanical Retrofits'),
        (202213, N'Thermal Systems'),
        (202215, N'Compression Molding (SMC)'),
        (202216, N'Mechanical Retrofits'),
        (202228, N'Press Lines / Cells'),
        (202234, N'Mechanical Retrofits'),
        (202245, N'Mechanical Retrofits'),
        (202251, N'Mechanical Retrofits'),
        (202295, N'Compression Molding (SMC)'),
        (202325, N'Pulp Bailing Press'),
        (202330, N'Compression Molding (SMC)'),
        (202336, N'Compression Molding (SMC)'),
        (202337, N'Compression Molding (SMC)'),
        (202342, N'Hydroforming / SPF'),
        (202349, N'Mechanical Retrofits'),
        (202351, N'Draw / Deep Draw'),
        (202360, N'Press'),
        (202365, N'Press'),
        (202369, N'Simulation & Process Dev'),
        (202374, N'Compression Molding (SMC)'),
        (202375, N'Press'),
        (202394, N'Metalforming'),
        (202418, N'Specialty Presses'),
        (202431, N'Metalforming'),
        (202434, N'Mechanical Retrofits'),
        (202436, N'Hydroforming / SPF'),
        (202445, N'Metalforming'),
        (202449, N'Press Lines / Cells'),
        (202453, N'Press'),
        (202454, N'Press'),
        (202469, N'Specialty Presses'),
        (202472, N'Metalforming'),
        (202480, N'Compression Molding (SMC)'),
        (202482, N'Mechanical Retrofits'),
        (202483, N'Non-Standard / Other'),
        (202484, N'Compression Molding (SMC)'),
        (210019, N'Press'),
        (210024, N'Specialty Presses'),
        (210026, N'Mechanical Retrofits'),
        (210031, N'Automation Systems'),
        (210061, N'Metalforming'),
        (210065, N'Pulp Bailing Press'),
        (210073, N'Compression Molding (SMC)'),
        (210140, N'Extrusion'),
        (210155, N'Extrusion'),
        (210169, N'Controls Retrofits'),
        (210205, N'Press'),
        (210206, N'Compression Molding (SMC)'),
        (210214, N'Compression Molding (SMC)'),
        (210242, N'Mechanical Retrofits'),
        (210275, N'Compression Molding (SMC)'),
        (210286, N'Mechanical Retrofits'),
        (210292, N'Specialty Presses'),
        (210307, N'Compression Molding (SMC)'),
        (210338, N'Press'),
        (210361, N'Compression Molding (SMC)'),
        (210375, N'Press'),
        (210412, N'Press'),
        (210428, N'Press'),
        (210447, N'Automation Systems'),
        (219999, N'R&D / Internal Projects'),
        (220006, N'Mechanical Retrofits'),
        (220035, N'Compression Molding (SMC)'),
        (220096, N'R&D / Internal Projects'),
        (220097, N'Compression Molding (SMC)'),
        (220109, N'Pulp Bailing Press'),
        (220203, N'Hot Stamping / Heated Platen'),
        (220220, N'Mechanical Retrofits'),
        (220234, N'Compression Molding (SMC)'),
        (220296, N'Non-Standard / Other'),
        (220317, N'Mechanical Retrofits'),
        (220324, N'Prototype / Testing'),
        (220352, N'Hydroforming / SPF'),
        (220359, N'Forging'),
        (220384, N'Mechanical Retrofits'),
        (220389, N'Press'),
        (230006, N'Pulp Bailing Press'),
        (230044, N'Hydroforming / SPF'),
        (230049, N'Engineering Studies'),
        (230070, N'Simulation & Process Dev'),
        (230080, N'Press'),
        (230084, N'Prototype / Testing'),
        (230092, N'Press Lines / Cells'),
        (230093, N'Automation Systems'),
        (230105, N'Mechanical Retrofits'),
        (230127, N'Extrusion'),
        (230129, N'Extrusion'),
        (230134, N'Forging'),
        (230149, N'Extrusion'),
        (230151, N'Controls Retrofits'),
        (230152, N'Hydroforming / SPF'),
        (230187, N'Extrusion'),
        (230196, N'Hot Stamping / Heated Platen'),
        (230204, N'Mechanical Retrofits'),
        (230206, N'Mechanical Retrofits'),
        (230219, N'Forging'),
        (240010, N'Prototype / Testing'),
        (240021, N'Metalforming'),
        (240033, N'Metalforming'),
        (240040, N'Draw / Deep Draw'),
        (240043, N'Extrusion'),
        (240044, N'Stretch Forming'),
        (240051, N'Draw / Deep Draw'),
        (240054, N'Press'),
        (240081, N'Prototype / Testing'),
        (240088, N'Press Lines / Cells'),
        (240115, N'Material Handling'),
        (240141, N'Extrusion'),
        (240146, N'Hydroforming / SPF'),
        (240148, N'Hydroforming / SPF'),
        (240154, N'Hot Stamping / Heated Platen'),
        (240160, N'Press'),
        (240166, N'Hot Stamping / Heated Platen'),
        (240218, N'Specialty Presses'),
        (240222, N'R&D / Internal Projects'),
        (240232, N'Hydroforming / SPF'),
        (240244, N'Compression Molding (SMC)'),
        (250005, N'Forging'),
        (250043, N'Non-Standard / Other'),
        (250099, N'Hydroforming / SPF'),
        (250130, N'Forging'),
        (250138, N'Press'),
        (250148, N'Press'),
        (250161, N'Draw / Deep Draw'),
        (250163, N'Non-Standard / Other'),
        (250164, N'Auxiliary Systems'),
        (250181, N'Hydroforming / SPF'),
        (250209, N'Simulation & Process Dev'),
        (250250, N'Compression Molding (SMC)'),
        (250251, N'Non-Standard / Other'),
        (250259, N'Press Lines / Cells'),
        (250269, N'Non-Standard / Other'),
        (250284, N'Press'),
        (250309, N'Non-Standard / Other'),
        (250340, N'Stretch Forming'),
        (260027, N'Simulation & Process Dev'),
        (260054, N'Hot Stamping / Heated Platen'),
        (260078, N'Non-Standard / Other'),
        (260079, N'Mechanical Retrofits'),
        (260087, N'Simulation & Process Dev'),
        (260115, N'Engineering Studies'),
        (260118, N'Specialty Presses'),
        (260168, N'Compression Molding (SMC)'),
        (260178, N'Press')
    ) AS src (ProjectID, Category)
WHERE NOT EXISTS (SELECT 1 FROM Reporting.tblProjectCategory pc WHERE pc.ProjectID = src.ProjectID);
GO

-- Run once as owner if the app/seed login lacks CREATE on the locked-down Reporting DB, then grant:
-- GRANT SELECT, INSERT, UPDATE, DELETE ON Reporting.tblProjectCategory       TO [<app login>];
-- GRANT SELECT, INSERT, UPDATE, DELETE ON Reporting.tlkpProjectCategoryGroup TO [<app login>];

-- Sanity (expect 224 classified, 26 categories, 7 groups):
--   SELECT COUNT(*) FROM Reporting.tblProjectCategory;
--   SELECT CategoryGroup, COUNT(*) FROM Reporting.tblProjectCategory pc
--     JOIN Reporting.tlkpProjectCategoryGroup g ON g.Category=pc.Category
--     GROUP BY CategoryGroup ORDER BY CategoryGroup;
