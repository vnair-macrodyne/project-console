"""
console_web/cache.py — warm in-memory cache for the heavy Dashboard payloads.

WHY
    Every /api/query for the Executive board / scorecard rebuilt a LiveQueryService
    and re-ran the live ETO timecard + PO aggregations (financials, project meta,
    NC-by-project, procurement, 2-week actuals) on *every* open — so the Dashboard
    "buffered" for a long time each time. This module keeps the computed exec +
    scorecard payloads warm in memory so requests serve instantly, and refreshes
    them in the background only when the underlying data has actually moved.

DESIGN (owner decision, 2026-07-27)
    * Background daemon thread, gated by a cheap data "watermark" (max ETO TimeID +
      max PO PurchaseDetailID + max Console-store edit time — see queries.data_watermark).
      Recompute only when the watermark moves; serve from memory otherwise.
    * ~30 s probe interval. A safety-net full recompute at least every MAX_AGE seconds
      catches the rare in-place edit that doesn't advance a max key. A PM budget / plan
      save calls mark_dirty() to wake the refresher immediately.
    * Requests read the warm cache (no DB round-trip) and get an `as_of` stamp the UI
      renders as "Updated Xs ago". Cold or custom-scope requests compute live once,
      cache the result, and register the scope as "hot" so the daemon keeps it warm.
    * Cache key is (query_id, sorted project ids) ONLY — exec/scorecard ignore the
      date window and view, so those are deliberately excluded so the browser's request
      and the primed entry always share a key.
    * One waitress process + thread pool -> one module-level singleton + one daemon
      thread. (If ever run under multiple worker processes, each keeps its own copy —
      fine for a read cache, just N recomputes.) Tenant-agnostic product core.
"""
from __future__ import annotations

import datetime as _dt
import threading

# Dashboard query ids that are cached/kept warm (they ignore date window + view).
HOT_QUERIES = ("exec", "scorecard")

INTERVAL = 30      # seconds between cheap change-probes
MAX_AGE = 300      # force a rebuild at least this often (safety net for silent edits)
MAX_HOT = 32       # cap on distinct scopes kept warm (evict oldest beyond this)


def _now():
    return _dt.datetime.now()


def _now_iso():
    return _now().isoformat(timespec="seconds")


class DashboardCache:
    def __init__(self, interval=INTERVAL, max_age=MAX_AGE):
        self.interval = interval
        self.max_age = max_age
        self._lock = threading.Lock()
        self._entries = {}          # key -> {"result", "watermark", "as_of", "ts"}
        self._hot = []              # ordered list of keys to keep warm (most-recent last)
        self._watermark = None      # last-known data watermark (maintained by the daemon)
        self._last_full = None      # time of the last full recompute
        self._wake = threading.Event()
        self._thread = None
        self._warm_fn = None
        self._watermark_fn = None

    # ── key ──────────────────────────────────────────────────────────────────
    @staticmethod
    def key(query_id, project_ids):
        return (query_id, tuple(sorted(int(p) for p in (project_ids or []))))

    # ── request-path reads ───────────────────────────────────────────────────
    def current_watermark(self):
        return self._watermark

    def get(self, key):
        with self._lock:
            e = self._entries.get(key)
            return dict(e) if e else None

    def put(self, key, result, watermark):
        """Store a computed payload; returns the as_of stamp assigned."""
        as_of = _now_iso()
        with self._lock:
            self._entries[key] = {"result": result, "watermark": watermark,
                                  "as_of": as_of, "ts": _now()}
        return as_of

    def remember(self, key):
        """Register a scope as hot so the daemon keeps it warm; cap the set."""
        with self._lock:
            if key in self._hot:
                self._hot.remove(key)
            self._hot.append(key)
            while len(self._hot) > MAX_HOT:
                dropped = self._hot.pop(0)
                self._entries.pop(dropped, None)

    def hot_keys(self):
        with self._lock:
            return list(self._hot)

    def mark_dirty(self):
        """Called after a PM budget / plan save — wake the refresher immediately."""
        self._wake.set()

    # ── background refresher ─────────────────────────────────────────────────
    def start(self, warm_fn, watermark_fn):
        """Idempotent. warm_fn(watermark) recomputes+stores the hot keys;
        watermark_fn() returns the cheap change-probe string."""
        with self._lock:
            if self._thread is not None:
                return
            self._warm_fn = warm_fn
            self._watermark_fn = watermark_fn
            # seed the watermark synchronously so the first request caches under a
            # real value (not None) and stays valid on the next hit.
            try:
                self._watermark = watermark_fn()
            except Exception:
                self._watermark = None
            self._thread = threading.Thread(target=self._loop, name="dash-cache",
                                            daemon=True)
            self._thread.start()

    def _loop(self):
        # prime once at startup so the first viewer gets a warm default board
        self._safe_refresh(force=True)
        while True:
            woken = self._wake.wait(timeout=self.interval)
            self._wake.clear()
            self._safe_refresh(force=woken)

    def _safe_refresh(self, force=False):
        try:
            self._refresh(force=force)
        except Exception:
            pass  # a daemon that dies stops all refreshes — never let it

    def _refresh(self, force=False):
        try:
            wm = self._watermark_fn()
        except Exception:
            wm = self._watermark
        age = ((_now() - self._last_full).total_seconds()
               if self._last_full else float("inf"))
        changed = (wm != self._watermark)
        if force or changed or age > self.max_age:
            self._warm_fn(wm)          # recompute the hot keys and put() them
            self._watermark = wm
            self._last_full = _now()


# Module-level singleton (one per process).
cache = DashboardCache()
