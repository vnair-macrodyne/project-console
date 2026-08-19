"""
console_seed_itemprice.py — refresh Reporting.tblItemPriceRef from ETO PO history.

Stages a HISTORICAL, median-picked purchase price per item into the Console store so the reporting
queries (Released—To Order today; material projection later) join a small local table instead of
re-aggregating ~160k PO lines on every run. BOM / release data stays LIVE from ETO — only the price
reference is staged.

Median (PERCENTILE_CONT 0.5) is robust to the odd outlier PO. Also stores the most-recent unit
price, line count (confidence), and date span. Full refresh (DELETE + reinsert) — the table is a
derived snapshot, not a versioned record.

Run on a host that can reach BOTH ETO and the Console store (the app host), scheduled nightly:
    python console_seed_itemprice.py            # refresh
    python console_seed_itemprice.py --dry-run  # compute + show a sample, no writes

Idempotent. If the table is missing it is created (matches sql/013_item_price_ref.sql).
"""
from __future__ import annotations

import argparse

import numpy as _np
import pandas as pd

import console_config  # noqa: F401 — loads .env into os.environ

DDL = """
IF OBJECT_ID('Reporting.tblItemPriceRef', 'U') IS NULL
CREATE TABLE Reporting.tblItemPriceRef (
    ItemID       INT            NOT NULL CONSTRAINT PK_tblItemPriceRef PRIMARY KEY,
    MedianUnit   DECIMAL(18,4)  NULL,
    LastUnit     DECIMAL(18,4)  NULL,
    LastPODate   DATE           NULL,
    POLines      INT            NULL,
    MinPODate    DATE           NULL,
    MaxPODate    DATE           NULL,
    RefreshedAt  DATETIME       NOT NULL CONSTRAINT DF_tblItemPriceRef_RefreshedAt DEFAULT (GETDATE())
);
"""

# Median + last + span per item, computed on ETO. Unit = the STORED unit price (pod.PurchasePrice —
# the same field PO Status shows as "Price"), FX-normalised to CAD via the PO's currency rate. We do
# NOT derive unit = ExtendedPrice/PurchaseQty: that swings ~1000x when an item is bought in different
# units of measure (each vs box-of-N), which poisons the median. Median is robust to the remaining
# real price dispersion.
QUERY = """
WITH u AS (
    SELECT pod.ItemID,
           CAST(pod.PurchasePrice AS float)
             * (CASE WHEN poh.PurchaseCurrRate > 0 THEN poh.PurchaseCurrRate ELSE 1 END) AS Unit,
           CAST(poh.PurchaseDate AS date) AS PODate
    FROM dbo.vwPurchaseOrderDetails pod
    JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
    WHERE pod.ItemID IS NOT NULL AND pod.PurchasePrice IS NOT NULL AND pod.PurchasePrice > 0
),
med AS (
    SELECT DISTINCT ItemID,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY Unit) OVER (PARTITION BY ItemID) AS MedianUnit
    FROM u
),
agg AS (
    SELECT ItemID, COUNT(*) AS POLines, MIN(PODate) AS MinPODate, MAX(PODate) AS MaxPODate
    FROM u GROUP BY ItemID
),
lastp AS (
    SELECT ItemID, Unit AS LastUnit, PODate AS LastPODate
    FROM (SELECT ItemID, Unit, PODate,
                 ROW_NUMBER() OVER (PARTITION BY ItemID ORDER BY PODate DESC) AS rn
          FROM u) z
    WHERE rn = 1
)
SELECT m.ItemID, m.MedianUnit, l.LastUnit, l.LastPODate, a.POLines, a.MinPODate, a.MaxPODate
FROM med m
JOIN agg   a ON a.ItemID = m.ItemID
JOIN lastp l ON l.ItemID = m.ItemID
"""


def _conns():
    try:
        from console.infra.connections import console_connection, eto_connection
        return console_connection(), eto_connection()
    except Exception:
        import console_store
        return console_store.console_connection(), console_store.eto_connection()


def _scrub(x):
    if isinstance(x, _np.generic):
        x = x.item()
    try:
        if x is None or pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return x


def fetch(eto):
    cur = eto.cursor()
    cur.execute(QUERY)
    cols = [d[0] for d in cur.description]
    return pd.DataFrame.from_records(cur.fetchall(), columns=cols)


def refresh(store, df):
    cur = store.cursor()
    # Create the table if we can. If the store login lacks CREATE rights (common on the locked-down
    # Reporting DB), that's fine AS LONG AS the table already exists (create it once via
    # sql/013_item_price_ref.sql in SSMS + grant INSERT/DELETE to the app login).
    try:
        cur.execute(DDL)
        store.commit()
    except Exception as e:
        try:
            store.rollback()
        except Exception:
            pass
        cur.execute("SELECT OBJECT_ID('Reporting.tblItemPriceRef', 'U')")
        if cur.fetchone()[0] is None:
            raise RuntimeError(
                "Reporting.tblItemPriceRef does not exist and this login cannot CREATE it "
                f"({type(e).__name__}). Create it once in SSMS with an owner account:\n"
                "    run sql/013_item_price_ref.sql,  then GRANT INSERT, DELETE ON "
                "Reporting.tblItemPriceRef TO <app login>;\n"
                "then re-run this refresh (which only needs INSERT/DELETE).") from e
        print("note: table exists; skipping CREATE (no CREATE right on this login).")
    cur.execute("DELETE FROM Reporting.tblItemPriceRef;")
    ins = ("INSERT INTO Reporting.tblItemPriceRef "
           "(ItemID, MedianUnit, LastUnit, LastPODate, POLines, MinPODate, MaxPODate) "
           "VALUES (?,?,?,?,?,?,?)")
    try:
        cur.fast_executemany = True
    except Exception:
        pass
    rows = [(_scrub(r.ItemID), _scrub(r.MedianUnit), _scrub(r.LastUnit), _scrub(r.LastPODate),
             _scrub(r.POLines), _scrub(r.MinPODate), _scrub(r.MaxPODate))
            for r in df.itertuples(index=False)]
    cur.executemany(ins, rows)
    store.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description="Refresh Reporting.tblItemPriceRef from ETO PO history.")
    ap.add_argument("--dry-run", action="store_true", help="Compute + show a sample; no DB writes")
    args = ap.parse_args()
    store, eto = _conns()
    try:
        df = fetch(eto)
        print(f"items priced from PO history: {len(df):,}")
        print(df.head(8).to_string(index=False))
        if args.dry_run:
            print("\n(dry run — no writes)")
            return
        n = refresh(store, df)
        print(f"\nReporting.tblItemPriceRef refreshed: {n:,} rows.")
    finally:
        for c in (store, eto):
            try:
                c.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
