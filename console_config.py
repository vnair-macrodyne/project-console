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
    product_name: str = "Sextant"             # white-labelable per tenant/reseller
    product_tagline: str = "The Data Console"  # descriptor shown beside the wordmark
    tenant_id: str = "macrodyne"
    environment: str = "prod"                 # prod | staging (set from $CONSOLE_ENV)
    company_name: str = "Macrodyne Technologies Inc."
    header_color: str = "1F3864"
    logo_path: str = ""                        # optional header logo URL (served from /static);
                                               # blank → the product-initials tile is shown instead
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

    # ── UI lexicon (display labels) ────────────────────────────────────────
    # Internally the model always uses the canonical terms ("discipline",
    # "crosswalk", …). These are the *display* labels the web UI, columns and
    # exports show, so each tenant reads its OWN nomenclature and never has to
    # learn ours. Defaults here are Macrodyne's existing workbook language — the
    # roll-up and its mapping are the "Asset Re-Code" (Data Validation B3:C40),
    # the source is the "Hour Description" — so the tool reads like the Carpedia
    # pack they already use. A different tenant overrides any subset in its
    # profile (e.g. "discipline":"Trade"); unspecified keys keep these defaults.
    lexicon: dict = field(default_factory=lambda: {
        "project": "Project",
        "projects": "Projects",
        "discipline": "Asset Re-Code",       # our "discipline" roll-up = their Asset Re-Code
        "crosswalk": "Asset Re-Code",         # the HourDescription→bucket mapping table
        "hour_description": "Hour Description",
        "labour": "Labour",
        "material": "Material",
        "scorecard": "Scorecard",
    })

    # ── output / dashboard ─────────────────────────────────────────────────
    output_root: str = r"\\MACRO-FILESVR\Projects\Reports"
    dashboard_week: str = "current"           # 'current' (from PM Entries) or 'YYYY-WW'

    # ── connection secrets (env only) ──────────────────────────────────────
    reporting_user: str | None = None         # $CONSOLE_STORE_USER
    reporting_pwd: str | None = None          # $CONSOLE_STORE_PWD

    # ── auth: AD login-form (LDAP bind) ────────────────────────────────────
    ldap_server: str | None = None            # $CONSOLE_LDAP_SERVER e.g. ldaps://dc01.macrodynepress.com
    ad_domain: str | None = None              # $CONSOLE_AD_DOMAIN    e.g. macrodynepress.com (UPN suffix)

    # ------------------------------------------------------------------ helpers
    def term(self, key: str) -> str:
        """Display label for a canonical term (falls back to the key itself)."""
        return self.lexicon.get(key, key.replace("_", " ").title())

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
        # a profile may override only *some* lexicon terms — merge onto defaults
        # so unspecified terms keep their canonical labels.
        if isinstance(data.get("lexicon"), dict):
            merged = dict(cls().lexicon)
            merged.update(data["lexicon"])
            prof.lexicon = merged
        # secrets always from env (never from the committed profile)
        prof.reporting_user = os.environ.get("CONSOLE_STORE_USER", prof.reporting_user)
        prof.reporting_pwd = os.environ.get("CONSOLE_STORE_PWD", prof.reporting_pwd)
        if os.environ.get("CONSOLE_STORE_TRUSTED") == "1":
            prof.use_windows_auth = True
        # Reporting-store target is env-selectable so the SAME build points at staging or
        # prod without a code change. ETO stays prod read-only (its own eto_* config), so
        # staging tests run against a staging Reporting copy + the live read-only ETO.
        #   CONSOLE_ENV=staging  -> default staging DB name (Macrodyne_Reporting_Staging)
        #   CONSOLE_STORE_SERVER / CONSOLE_STORE_DB -> explicit override (win over CONSOLE_ENV)
        if os.environ.get("CONSOLE_ENV", "").lower() in ("staging", "stage", "test"):
            prof.reporting_database = "Macrodyne_Reporting_Staging"
        prof.reporting_server = os.environ.get("CONSOLE_STORE_SERVER", prof.reporting_server)
        prof.reporting_database = os.environ.get("CONSOLE_STORE_DB", prof.reporting_database)
        # ETO source is likewise env-selectable so a build running off-box (e.g. Azure App
        # Service reaching the ETO SQL Server over the VPN, possibly by host,port) can point at
        # the right address without a profile edit. Unset → the profile/default (unchanged
        # on-prem). Still read-only; only the address/name move, not the access mode.
        #   CONSOLE_ETO_SERVER / CONSOLE_ETO_DB -> explicit override (win over the profile)
        prof.eto_server = os.environ.get("CONSOLE_ETO_SERVER", prof.eto_server)
        prof.eto_database = os.environ.get("CONSOLE_ETO_DB", prof.eto_database)
        prof.environment = os.environ.get("CONSOLE_ENV", "prod").lower()
        # auth (LDAP) config — env wins over profile
        prof.ldap_server = os.environ.get("CONSOLE_LDAP_SERVER", prof.ldap_server)
        prof.ad_domain = os.environ.get("CONSOLE_AD_DOMAIN", prof.ad_domain)
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
