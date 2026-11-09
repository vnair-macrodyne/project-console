"""Unit tests for console/domain/tracked.py on in-memory SQLite (schema attached as 'Reporting').
Run:  python -m unittest tests.test_tracked -v"""
import sqlite3
import unittest

from console.domain.tracked import TrackedProjectDAO, TrackedSchemaMissing


class _Cur:                       # pyodbc-style execute(sql, *params) over sqlite3
    def __init__(self, c): self.c = c
    def execute(self, sql, *p): self.c.execute(sql, p); return self
    def fetchone(self): return self.c.fetchone()
    def fetchall(self): return self.c.fetchall()
    def fetchmany(self, n): return self.c.fetchmany(n)


class _Conn:
    def __init__(self, switch=True):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("ATTACH DATABASE ':memory:' AS Reporting")
        extra = (", IsActive INT NOT NULL DEFAULT 1, AddedBy TEXT, AddedAt TEXT, ChangedBy TEXT, "
                 "ChangedAt TEXT") if switch else ""
        self.db.execute("CREATE TABLE Reporting.tblActiveProject (ProjectID INT PRIMARY KEY, "
                        "Customer TEXT, Priority INT, Source TEXT, ImportedAt TEXT" + extra + ")")
        self.db.execute("CREATE TABLE Reporting.tblConsoleProjectExclusion (ProjectID INT PRIMARY KEY, "
                        "ExcludedAt TEXT, ExcludedBy TEXT)")
        if switch:
            self.db.execute("CREATE TABLE Reporting.tblTrackedProjectLog (LogID INTEGER PRIMARY KEY "
                            "AUTOINCREMENT, ProjectID INT, Action TEXT, Detail TEXT, ChangedBy TEXT, ChangedAt TEXT)")
    def cursor(self): return _Cur(self.db.cursor())
    def commit(self): self.db.commit()
    def rollback(self): self.db.rollback()
    def q(self, sql): return self.db.execute(sql).fetchall()


class TrackedTests(unittest.TestCase):
    def setUp(self):
        self.c = _Conn()
        self.d = TrackedProjectDAO(self.c)

    def order(self):
        return [r["id"] for r in self.d.rows()]

    def test_seed_then_add_remove_reorder(self):
        r = self.d.replace_all([250005, 250161, 220154, 250161], user="seed")   # dup ignored
        self.assertEqual(r["tracked"], [250005, 250161, 220154])
        self.assertEqual(self.order(), [250005, 250161, 220154])
        self.assertTrue(self.d.activate(260079, "mike"))          # appended last
        self.assertFalse(self.d.activate(260079, "mike"))         # idempotent
        self.assertEqual(self.order()[-1], 260079)
        self.assertTrue(self.d.deactivate(250161, "helen"))       # removed + compacted
        self.assertEqual([(r["id"], r["priority"]) for r in self.d.rows()],
                         [(250005, 1), (220154, 2), (260079, 3)])
        self.assertEqual(self.c.q("SELECT ProjectID FROM Reporting.tblConsoleProjectExclusion"), [(250161,)])
        self.assertEqual(self.d.active_ids(), {250005, 220154, 260079})
        self.d.reorder([260079, 250005, 220154], "helen")
        self.assertEqual(self.order(), [260079, 250005, 220154])
        with self.assertRaises(ValueError):
            self.d.reorder([260079, 250005], "helen")            # incomplete order refused
        self.assertTrue(self.d.activate(250161, "mike"))          # re-add: history kept, exclusion cleared
        self.assertEqual(self.c.q("SELECT COUNT(*) FROM Reporting.tblConsoleProjectExclusion"), [(0,)])
        self.assertEqual(self.order()[-1], 250161)
        self.assertEqual(self.d.rows(include_removed=True)[-1]["id"], 250161)
        acts = [h["action"] for h in self.d.history()]
        self.assertEqual(acts[0], "add")
        self.assertIn("reorder", acts)
        self.assertEqual(acts.count("seed-add"), 3)

    def test_reseed_removes_unlisted(self):
        self.d.replace_all([1, 2, 3], "seed")
        r = self.d.replace_all([3, 4], "seed")
        self.assertEqual(r["removed"], [1, 2]); self.assertEqual(r["added"], [4]); self.assertEqual(r["kept"], [3])
        self.assertEqual([(x["id"], x["priority"]) for x in self.d.rows()], [(3, 1), (4, 2)])

    def test_failed_write_rolls_back(self):
        self.d.replace_all([1, 2], "seed")
        self.c.db.execute("DROP TABLE Reporting.tblTrackedProjectLog")     # make the log insert fail
        with self.assertRaises(Exception):
            self.d.deactivate(1, "x")
        self.assertEqual(self.d.active_ids(), {1, 2})

    def test_pre_migration_reads_work_writes_refuse(self):
        c = _Conn(switch=False)
        c.db.execute("INSERT INTO Reporting.tblActiveProject (ProjectID, Priority) VALUES (5, 1), (6, NULL)")
        c.commit()
        d = TrackedProjectDAO(c)
        self.assertEqual(d.active_ids(), {5, 6})
        self.assertEqual([r["id"] for r in d.rows()], [5, 6])
        with self.assertRaises(TrackedSchemaMissing):
            d.activate(7)


if __name__ == "__main__":
    unittest.main()
