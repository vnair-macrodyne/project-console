"""
DB parameter scrubbing — the single guard that makes any value pyodbc-safe.

Every parameterised write in the DAOs goes through `ex`/`exmany`, so a numpy scalar,
NaN, NaT, or pandas NA can never reach the SQL driver as an invalid data type
(the class of error that shows up as "not a valid instance of data type float").
"""
import numpy as np
import pandas as pd


def scrub(x):
    """numpy scalar → native python; NaN/NaT/NA → None; everything else unchanged."""
    if isinstance(x, np.generic):
        x = x.item()
    try:
        if x is None or pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return x


def ex(cur, sql, *params):
    """cursor.execute with every bound parameter scrubbed."""
    return cur.execute(sql, *[scrub(p) for p in params])


def exmany(cur, sql, rows):
    """cursor.executemany with every value in every row scrubbed."""
    return cur.executemany(sql, [tuple(scrub(v) for v in row) for row in rows])
