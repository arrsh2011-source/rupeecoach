"""Render reports to a single self-contained HTML file (light/dark, mobile-friendly)."""

from __future__ import annotations

import json
from importlib.resources import files

from truecap.domain import FactSet, Stage
from truecap.report import NarrativeDraft, Report, build_report
from truecap.checks import CheckContext


def stage_variants(name: str, facts: FactSet, ctx: CheckContext, narrative: NarrativeDraft | None,
                   inferred: Report) -> dict[str, dict]:
    """The report under every stage's weights, so the page can switch stage with no new research."""
    out = {"auto": inferred.model_dump(mode="json")}
    for st in Stage:
        r = build_report(name, facts, ctx, stage_override=st, narrative=narrative, generated_at=inferred.generated_at)
        r.guard_log = inferred.guard_log
        out[st.value] = r.model_dump(mode="json")
    return out


def render_html(companies: dict[str, tuple[str, dict[str, dict]]], sample: bool = False) -> str:
    """companies: key -> (label, stage_variants)."""
    data = {"sample": sample,
            "companies": {k: {"label": label, "reports": reports} for k, (label, reports) in companies.items()}}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = files("truecap.render").joinpath("report.html").read_text(encoding="utf-8")
    page = template.replace("/*DATA*/", payload)
    # The template is written as an artifact body; give it a full document wrapper for standalone use.
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            "<style>body{margin:0}[hidden]{display:none!important}</style>"
            f"</head><body>{page}</body></html>")
