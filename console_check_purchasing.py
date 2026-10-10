"""
console_check_purchasing.py — live check of the four Purchasing reports after the 2026-10-10 rework.
READ-ONLY. Run on the office machine (ETO + Reporting reachable) BEFORE deploying.

Runs Lines to Order, Purchase Requisitions, PO Exceptions and All Purchase Orders LIVE for the
sample projects, times each, prints the cards, the columns, and counts by Release Stage — and, for
Lines to Order, how many rows are partial / ordered on another machine. Also confirms the
Lines to Order total ties to the 2026-10-09 probe (518 unordered + partials on the same projects;
the new rule is per machine and by quantity, so the count should be HIGHER than 518, with every
partial carrying OrderedQty > 0).

Run:  python console_check_purchasing.py                 # 260178 250005 220154
      python console_check_purchasing.py 250005          # or name projects
Paste the whole output back.
"""
import sys, time
from collections import Counter

PIDS = [int(a) for a in sys.argv[1:] if a.isdigit()] or [260178, 250005, 220154]


def main():
    from console_web.queries import LiveQueryService
    print(f"console_check_purchasing — {time.strftime('%Y-%m-%d %H:%M')}  projects {PIDS}")
    for qid in ("released_toorder", "po_to_order", "po_exceptions", "po_listing"):
        s = LiveQueryService()
        t0 = time.perf_counter()
        try:
            r = s.run(qid, PIDS)
        except Exception as e:
            print(f"\n== {qid}: FAILED — {type(e).__name__}: {e}")
            continue
        dt = time.perf_counter() - t0
        r.to_dict()                                   # must serialise for the web page
        det = [x for x in r.rows if x.get("_kind") == "detail"]
        print(f"\n== {r.title}  ({dt:.1f}s, {len(det):,} detail rows)")
        print("   cards  : " + " · ".join(f"{c.label} {c.value}" for c in r.cards))
        print("   columns: " + ", ".join(c.label for c in r.columns))
        st = Counter(str(x.get("Stage")) for x in det)
        print("   Release Stage: " + ", ".join(f"{k} {v:,}" for k, v in st.most_common()))
        if qid == "released_toorder":
            part = sum(1 for x in det if (x.get("OrderedQty") or 0) > 0)
            other = sum(1 for x in det if (x.get("OrderedElsewhere") or 0) > 0)
            stock = sum(1 for x in det if (x.get("OnHand") or 0) >= (x.get("ToOrder") or 0) > 0)
            print(f"   partly ordered {part:,} · ordered on another machine {other:,} · "
                  f"on-hand covers To Order {stock:,}")
            for x in det[:5]:
                print(f"     {x.get('ProjectID')} {x.get('Machine'):>4} {str(x.get('ItemNo')):22} "
                      f"rel {x.get('Qty')} ord {x.get('OrderedQty')} to-order {x.get('ToOrder')} {x.get('Stage')}")
    print("\nDONE — paste everything above.")


if __name__ == "__main__":
    main()
