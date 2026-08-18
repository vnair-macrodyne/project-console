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

# Median + last + span per item, computed on ETO. Unit = ExtendedPrice / PurchaseQty on real,
# positive-qty, priced lines. (Currency is as ETO stores ExtendedPrice — same basis the report used
# before; FX-normalising to CAD is a later refinement, noted in the project doc.)
QUERY = """
WITH u AS (
    SELECT pod.ItemID,
           CAST(pod.ExtendedPrice AS float) / NULLIF(CAST(pod.PurchaseQty AS float), 0) AS Unit,
           CAST(poh.PurchaseDate AS date) AS PODate
    FROM dbo.vwPurchaseOrderDetails pod
    JOIN dbo.vwPurchaseOrderHeader poh ON poh.PurchaseOrderID = pod.PurchaseOrderID
    WHERE pod.ItemID IS NOT NULL AND pod.PurchaseQty > 0
      AND pod.ExtendedPrice IS NOT NULL AND pod.ExtendedPrice > 0
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
    cur.execute(DDL)
    store.commit()
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
