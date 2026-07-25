"""
console_diag_recon.py — does the discipline hours block reconcile? (read-only)

Confirms the Asset Re-Code crosswalk isn't leaking live HourDescriptions into 'Other',
and that timecard hours-by-discipline sum to the project's total actual labour hours.

For each project prints: actual hours per discipline (incl. Other), the timecard grand
total, the estimate-view actual total (should match), and the delta. Then lists any
HourDescriptions in the data that are NOT in the crosswalk (they fall to Other).

Run:  python console_diag_recon.py 230219,240033,240148,240040,250250,240218,250217,240154,240088,220154
Paste the output back.
"""
import sys
import pandas as pd

from console_engine import _connect, _run, q_actual_hours_by_hourtype, q_estimate_vs_actual
from console_feed import DISCIPLINE_MAP, UNMAPPED_DISCIPLINE, DISCIPLINES


def main():
    pids = [int(p) for p in (sys.argv[1] if len(sys.argv) > 1
            else "230219,240033").split(",") if p.strip()]
    conn = _connect()
    try:
        cur = conn.cursor()
        raw = _run(cur, q_actual_hours_by_hourtype(pids))          # ProjectID, HourDescription, ActHours
        ev  = _run(cur, q_estimate_vs_actual(pids))                # has ActAdmin/Eng/MfgHours
    finally:
        conn.close()

    raw["ActHours"] = raw["ActHours"].astype(float)
    raw["Discipline"] = raw["HourDescription"].map(DISCIPLINE_MAP).fillna(UNMAPPED_DISCIPLINE)

    # estimate-view total actual hours per project (the number to reconcile against)
    ev = ev.set_index("ProjectID")
    def ev_total(pid):
        if pid not in ev.index:
            return None
        r = ev.loc[pid]
        return float(r.ActAdminHours or 0) + float(r.ActEngHours or 0) + float(r.ActMfgHours or 0)

    print(f"{'Project':>8} | " + "".join(f"{d.split()[0][:5]:>8}" for d in DISCIPLINES)
          + f" | {'TC tot':>9} {'EstView':>9} {'Δ':>8}")
    for pid, g in raw.groupby("ProjectID"):
        by = g.groupby("Discipline")["ActHours"].sum()
        tc_total = float(g["ActHours"].sum())
        evt = ev_total(pid)
        cells = "".join(f"{by.get(d, 0):>8.0f}" for d in DISCIPLINES)
        delta = "" if evt is None else f"{tc_total - evt:>8.0f}"
        print(f"{pid:>8} | {cells} | {tc_total:>9.0f} {('' if evt is None else f'{evt:>9.0f}')} {delta}")

    # % of hours landing in Other, and the offending descriptions
    other = raw[raw["Discipline"] == UNMAPPED_DISCIPLINE]
    tot = raw["ActHours"].sum()
    print(f"\nTotal actual hours across all listed projects: {tot:,.0f}")
    print(f"Hours mapped to 'Other': {other['ActHours'].sum():,.0f} "
          f"({(other['ActHours'].sum()/tot if tot else 0):.1%})")
    unmapped = (other.groupby("HourDescription")["ActHours"].sum()
                .sort_values(ascending=False))
    print("\nHourDescriptions falling to 'Other' (NOT in the crosswalk = leakage; "
          "in-crosswalk NC items are legitimately Other):")
    for hd, h in unmapped.items():
        tag = "  <-- NOT IN CROSSWALK" if hd not in DISCIPLINE_MAP else ""
        print(f"    {h:>10,.0f}  {hd}{tag}")


if __name__ == "__main__":
    main()
