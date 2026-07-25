"""
Project Console — config access for the layered package.
Re-exports the tenant profile so package modules import from one place
(`console.config`) without reaching back to the flat module during migration.
"""
from console_config import TenantProfile, TENANT  # noqa: F401
