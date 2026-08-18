-- sql/013_item_price_ref.sql — Console store reference table for item purchase prices.
-- Staged (seeded) from ETO PO history by console_seed_itemprice.py so the reporting queries
-- (Released—To Order today; material projection later) join a small local table instead of
-- re-aggregating ~160k PO lines on every run. Prices are HISTORICAL, median-picked (robust to
-- outliers). BOM / release data stays LIVE from ETO — only the price reference is staged.
-- Idempotent: safe to re-run. Run in the Macrodyne_Reporting DB (store connection is already there).

IF OBJECT_ID('Reporting.tblItemPriceRef', 'U') IS NULL
CREATE TABLE Reporting.tblItemPriceRef (
    ItemID       INT            NOT NULL
                 CONSTRAINT PK_tblItemPriceRef PRIMARY KEY,
    MedianUnit   DECIMAL(18,4)  NULL,      -- median historical PO unit price (ExtendedPrice / Qty)
    LastUnit     DECIMAL(18,4)  NULL,      -- most-recent PO unit price
    LastPODate   DATE           NULL,      -- date of that most-recent PO line
    POLines      INT            NULL,      -- # PO lines the median is drawn from (confidence)
    MinPODate    DATE           NULL,
    MaxPODate    DATE           NULL,
    RefreshedAt  DATETIME       NOT NULL
                 CONSTRAINT DF_tblItemPriceRef_RefreshedAt DEFAULT (GETDATE())
);
