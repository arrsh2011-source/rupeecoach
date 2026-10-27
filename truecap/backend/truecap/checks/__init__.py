"""Importing this package registers every check in `REGISTRY`."""

from truecap.checks import financials, legal, market, team, traction  # noqa: F401
from truecap.checks.base import REGISTRY, CheckContext, CheckSpec

__all__ = ["REGISTRY", "CheckContext", "CheckSpec", "run_all"]


def run_all(facts, ctx: CheckContext | None = None):
    ctx = ctx or CheckContext()
    return [spec.run(facts, ctx) for spec in REGISTRY.values()]
