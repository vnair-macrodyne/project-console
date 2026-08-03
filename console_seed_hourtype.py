"""
console_seed_hourtype.py — one-time: create + seed Reporting.tlkpHourTypeDiscipline.

Silences the benign startup WARNING:
    Invalid object name 'Reporting.tlkpHourTypeDiscipline'
The app already falls back to deriving this HourType->discipline map live from ETO, so results
are unaffected — this just materialises the map in the Console store so it loads from there and
the warning stops. Idempotent: safe to re-run (human Source='manual' overrides are preserved by
the merge in HourTypeDisciplineDAO.seed_from_eto).

Run once on a machine that can reach BOTH the Console store and ETO (e.g. the app host):
    python console_seed_hourtype.py

No app restart needed — each request loads the map fresh, so the next dashboard hit reads the
table and the warning stops. If the store account lacks CREATE rights, run sql/008 in SSMS first,
then re-run this to seed.
"""

# Matches sql/008_hourtype_discipline.sql (USE/GO stripped; the store connection is already on
# the reporting DB). A single IF ... CREATE batch, so pyodbc runs it directly.
DDL = """
IF OBJECT_ID('Reporting.tlkpHourTypeDiscipline', 'U') IS NULL
CREATE TABLE Reporting.tlkpHourTypeDiscipline (
    HourType        INT           NOT NULL
                    CONSTRAINT PK_tlkpHourTypeDiscipline PRIMARY KEY,
    HourDescription NVARCHAR(80)  NULL,
    Discipline      NVARCHAR(40)  NOT NULL,
    Source          NVARCHAR(20)  NOT NULL
                    CONSTRAINT DF_tlkpHourTypeDiscipline_Source DEFAULT ('ETO'),
    UpdatedAt       DATETIME      NOT NULL
                    CONSTRAINT DF_tlkpHourTypeDiscipline_UpdatedAt DEFAULT (GETDATE())
);
"""


def _conns():
    """(store, eto) using the same connectors the app uses; fall back to console_store."""
    try:
        from console.infra.connections import console_connection, eto_connection
        return console_connection(), eto_connection()
    except Exception:
        import console_store
        return console_store.console_connection(), console_store.eto_connection()


def main():
    from console.domain.hourtype_map import HourTypeDisciplineDAO
    store, eto = _conns()
    try:
        # 1) create the table if missing
        cur = store.cursor()
        cur.execute(DDL)
        store.commit()
        print("table ready : Reporting.tlkpHourTypeDiscipline")

        dao = HourTypeDisciplineDAO(store)
        print(f"rows before : {len(dao.load_map())}")

        # 2) seed from ETO's controlled hour types (manual overrides preserved)
        n = dao.seed_from_eto(eto)
        print(f"processed   : {n} ETO hour types")

        # 3) verify + show the resulting split
        m = dao.load_map()
        print(f"rows after  : {len(m)}")
        from collections import Counter
        print("discipline distribution:")
        for disc, c in sorted(Counter(m.values()).items(), key=lambda x: -x[1]):
            print(f"  {c:3}  {disc}")
        print("\nDone. No restart needed — the warning stops on the next dashboard load.")
    finally:
        for c in (store, eto):
            try:
                c.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
