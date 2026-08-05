"""
earned_value.py — the run-out (Estimate at Completion) engine.

Pure functions implementing PROJECT_CONSOLE_RUNOUT_METHODOLOGY_2026-07-28. Given a budget (BAC),
actual-to-date (AC) and percent-complete (%C, PM-entered), it derives the earned-value position:
EV, CPI, run-out (EAC), run-out %, variance at completion (VAC) and TCPI — with the methodology's
guardrails so we never divide by zero or over-trust an early %C.

Basis is HOURS for the labour headline (clean comparator); the same math serves $ when passed $.
No I/O — trivially unit-testable (see the worked example in the methodology doc).
"""
from dataclasses import dataclass

EARLY_STAGE_PCT = 0.15      # below this, use the additive EAC and flag low confidence
GREEN_MAX = 0.95            # run-out % thresholds (EAC ÷ BAC)
AMBER_MAX = 1.05


@dataclass(frozen=True)
class RunOut:
    bac: float | None                 # Budget at Completion (authorised)
    ac: float | None                  # Actual to date
    pct_complete: float | None        # %C as a 0–1 fraction
    ev: float | None = None           # Earned Value = %C × BAC
    cpi: float | None = None          # EV ÷ AC   (<1 = trending over)
    eac: float | None = None          # run-out = AC ÷ %C  (Estimate at Completion)
    runout_pct: float | None = None   # EAC ÷ BAC
    vac: float | None = None          # BAC − EAC  (negative = projected overrun)
    tcpi: float | None = None         # efficiency needed on remaining work to hit BAC
    consumed_pct: float | None = None # AC ÷ BAC   (spend-to-date, for contrast)
    confidence: str = "none"          # none | low (early stage) | ok
    status: str = "neutral"           # neutral | good | warn | bad  (drives the tile colour)
    note: str = ""                    # short human reason when the number is caveated


def _status(runout_pct):
    if runout_pct is None:
        return "neutral"
    if runout_pct <= GREEN_MAX:
        return "good"
    if runout_pct <= AMBER_MAX:
        return "warn"
    return "bad"


def compute(bac, ac, pct_complete) -> RunOut:
    """Derive the run-out position. Inputs may be None; the result degrades gracefully.

    pct_complete is a 0–1 fraction. Returns a RunOut with everything the dashboard needs to
    render a live run-out and its at-risk colour, plus a confidence/note for the edge cases the
    methodology calls out (no budget, started-but-no-progress, early stage, complete)."""
    b = _f(bac)
    a = _f(ac)
    p = _f(pct_complete)
    consumed = (a / b) if (b and a is not None) else None

    if not b:                                             # no authorised budget → nothing to run out
        return RunOut(b, a, p, consumed_pct=consumed, confidence="none",
                      note="no budget")
    ev = (p * b) if p is not None else None
    if p is None or p <= 0:                               # started, no progress → don't divide by zero
        started = bool(a)
        return RunOut(b, a, p, ev=ev, consumed_pct=consumed,
                      confidence="none", status="bad" if started else "neutral",
                      note="started, no % complete" if started else "no % complete")
    if p >= 1.0:                                          # complete → EAC = AC
        eac = a or b
        return RunOut(b, a, 1.0, ev=b, cpi=((b / a) if a else None), eac=eac,
                      runout_pct=(eac / b), vac=(b - eac), tcpi=None,
                      consumed_pct=consumed, confidence="ok", status=_status(eac / b),
                      note="complete")

    cpi = (ev / a) if a else None
    if p < EARLY_STAGE_PCT:                               # early stage → additive EAC, low confidence
        eac = (a or 0.0) + (b - ev)
        conf, note = "low", f"early stage (<{int(EARLY_STAGE_PCT*100)}% complete)"
    else:                                                 # steady state → CPI run-out
        eac = a / p
        conf, note = "ok", ""
    runout_pct = eac / b
    vac = b - eac
    tcpi = ((b - ev) / (b - a)) if (a is not None and (b - a) != 0) else None
    return RunOut(b, a, p, ev=ev, cpi=cpi, eac=round(eac, 2), runout_pct=round(runout_pct, 4),
                  vac=round(vac, 2), tcpi=(round(tcpi, 4) if tcpi is not None else None),
                  consumed_pct=(round(consumed, 4) if consumed is not None else None),
                  confidence=conf, status=_status(runout_pct), note=note)


def earning_at_completion(sales_price, labour_cost_eac, material_eac, other=0.0):
    """Earning at completion = Sold Price − Cost EAC; margin = Earning ÷ Sold Price.
    Returns (earning, margin) — margin None when there's no sold price. $ basis (applied-rate)."""
    sp = _f(sales_price)
    cost = sum(x for x in (_f(labour_cost_eac), _f(material_eac), _f(other)) if x is not None)
    if sp is None:
        return None, None
    earning = sp - cost
    return round(earning, 2), (round(earning / sp, 4) if sp else None)


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None
