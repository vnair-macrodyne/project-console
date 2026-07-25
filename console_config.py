"""
console_config.py
==================
Tenant profile — the single home for everything that differs between Total ETO
customers. The product core reads from here; nothing Macrodyne-specific is hard-coded
elsewhere. A new customer = a new profile (JSON) + the install scripts (see
CARPEDIA_PRODUCT_ARCHITECTURE.md).

Load order:
  1. defaults below (Macrodyne),
  2. a JSON file at $CONSOLE_TENANT (or passed to load()),
  3. selected env overrides (connection secrets).
Secrets (passwords) come from env only — never commit them to a profile file.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict

# Load a local .env (repo root / cwd) into the environment before the profile reads
# it, so secrets live in a gitignored .env file. Harmless if python-dotenv or .env absent.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


@dataclass
class TenantProfile:
    # ── identity / branding ────────────────────────────────────────────────
    product_name: str = "Project Console"     # white-labelable per tenant/reseller
    tenant_id: str = "macrodyne"
    company_name: str = "Macrodyne Technologies Inc."
    header_color: str = "1F3864"
    confidential_footer: str = "CONFIDENTIAL — Internal Use Only"

    # ── ETO (vendor) source — READ ONLY ────────────────────────────────────
    eto_server: str = r"MACRO-ETO-SVR\SQLEXPRESS"
    eto_database: str = "Macrodyne_Production"

    # ── Reporting (customer-owned) store ───────────────────────────────────
    reporting_server: str = r"MACRO-ETO-SVR\SQLEXPRESS"
    reporting_database: str = "Macrodyne_Reporting"
    use_windows_auth: bool = False   # else SQL auth from env creds

    # ── fiscal calendar / periods ──────────────────────────────────────────
    fiscal_year_start_month: int = 4          # Macrodyne FY starts April 1
    pay_period_anchor: str = "2026-07-06"     # a known pay-period start (Monday)
    pay_period_days: int = 14
    week_numbering: str = "excel"             # match Excel WEEKNUM (dashboard keys)

    # ── project-number scheme ──────────────────────────────────────────────
    capital_min: int = 190000
    capital_max: int = 269999
    legacy_capital_below: int = 190000
    service_min: int = 500000
    active_min_hours: float = 4.0             # "active" = charged > this in the window

    # ── Project Console disciplines (roll-up buckets) ─────────────────────────────
    disciplines: list = field(default_factory=lambda: [
        "Project Management", "Mechanical Engineering", "Hydraulic Engineering",
        "Electrical Engineering", "Manufacturing", "Other"])

    # ── output / dashboard ─────────────────────────────────────────────────
    output_root: str = r"\\MACRO-FILESVR\Projects\Reports"
    dashboard_week: str = "current"           # 'current' (from PM Entries) or 'YYYY-WW'

    # ── connection secrets (env only) ──────────────────────────────────────
    reporting_user: str | None = None         # $CONSOLE_STORE_USER
    reporting_pwd: str | None = None          # $CONSOLE_STORE_PWD

    # ------------------------------------------------------------------ helpers
    def is_service(self, project_id: int) -> bool:
        return int(project_id) >= self.service_min

    def is_capital(self, project_id: int) -> bool:
        return self.capital_min <= int(project_id) <= self.capital_max

    def project_class(self, project_id: int) -> str:
        pid = int(project_id)
        if pid >= self.service_min:
            return "service"
        if pid < self.legacy_capital_below:
            return "legacy_capital"
        return "capital"

    def reporting_conn_str(self) -> str:
        base = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={self.reporting_server};"
                f"Database={self.reporting_database};")
        if self.use_windows_auth:
            return base + "Trusted_Connection=yes;"
        return base + f"UID={self.reporting_user};PWD={self.reporting_pwd};"

    def to_json(self, path: str, redact_secrets: bool = True):
        d = asdict(self)
        if redact_secrets:
            d.pop("reporting_user", None)
            d.pop("reporting_pwd", None)
        with open(path, "w") as f:
            json.dump(d, f, indent=2)
        return path

    @classmethod
    def load(cls, path: str | None = None) -> "TenantProfile":
        """defaults → JSON profile ($CONSOLE_TENANT or `path`) → env secret overrides."""
        data = {}
        path = path or os.environ.get("CONSOLE_TENANT")
        if path and os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
        known = set(cls.__dataclass_fields__)
        prof = cls(**{k: v for k, v in data.items() if k in known})
        # secrets always from env (never from the committed profile)
        prof.reporting_user = os.environ.get("CONSOLE_STORE_USER", prof.reporting_user)
        prof.reporting_pwd = os.environ.get("CONSOLE_STORE_PWD", prof.reporting_pwd)
        if os.environ.get("CONSOLE_STORE_TRUSTED") == "1":
            prof.use_windows_auth = True
        return prof


# The active profile for this process (Macrodyne default until a profile is loaded).
TENANT = TenantProfile.load()


if __name__ == "__main__":
    import sys
    p = TenantProfile.load(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Tenant: {p.tenant_id} ({p.company_name})")
    print(f"  ETO:       {p.eto_server} / {p.eto_database}  (read-only)")
    print(f"  Reporting: {p.reporting_server} / {p.reporting_database}")
    print(f"  FY starts month {p.fiscal_year_start_month}; capital {p.capital_min}-{p.capital_max}; service >= {p.service_min}")
    print(f"  230219 -> {p.project_class(230219)};  510000 -> {p.project_class(510000)}")