"""Command line: run real research on a company and save the report.

    truecap research "Company name" [--city Bengaluru] [--website site.com] [--cin U...] [--stage seed]
    truecap probe-datagov <resource_id>     # show the field names a data.gov.in dataset returns
    truecap demo-html                       # render the fictional sample companies
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import httpx

from truecap.checks import CheckContext
from truecap.config import get_settings
from truecap.domain import Stage
from truecap.render import render_html, stage_variants
from truecap.research.budget import Budget, BudgetExceeded
from truecap.research.llm import AnthropicLLM
from truecap.research.pipeline import Deps, NeedsPick, NotFound, ResearchQuery, research
from truecap.research.sources.registry import RegistryClient
from truecap.research.sources.website import WebsiteFetcher


def make_deps(http: httpx.Client) -> Deps:
    s = get_settings()
    llm = AnthropicLLM(s.anthropic_api_key, s.writing_model) if s.anthropic_api_key else None
    return Deps(
        llm=llm,
        registry=RegistryClient(s.data_gov_in_api_key, s.data_gov_in_resource_ids.split(","), http),
        website=WebsiteFetcher(http, s.user_agent, s.max_website_pages),
        budget=Budget(cap_inr=s.monthly_llm_budget_inr, usd_to_inr=s.usd_to_inr),
        extraction_model=s.extraction_model,
        writing_model=s.writing_model,
        max_web_searches=s.max_web_searches,
        narrative_enabled=s.narrative_enabled,
        established_investors=frozenset(s.established_investors),
    )


def cmd_research(args: argparse.Namespace) -> int:
    s = get_settings()
    if not s.anthropic_api_key and not s.data_gov_in_api_key:
        print("No keys configured. Set TRUECAP_ANTHROPIC_API_KEY (and ideally TRUECAP_DATA_GOV_IN_API_KEY) in .env.")
        return 2
    q = ResearchQuery(name=args.name, city=args.city, website=args.website, cin=args.cin,
                      stage_override=Stage(args.stage) if args.stage else None)
    with httpx.Client(timeout=s.http_timeout_seconds, headers={"User-Agent": s.user_agent}) as http:
        deps = make_deps(http)
        try:
            out = research(q, deps, progress=lambda step, pct, msg: print(f"[{pct:3d}%] {msg}", flush=True))
        except NeedsPick as e:
            print("\nSeveral companies match. Re-run with --cin for the one you mean:\n")
            for c in e.candidates:
                print(f"  {c.cin}  {c.name}  {c.place or ''}  {c.status or ''}")
            return 3
        except (NotFound, BudgetExceeded) as e:
            print(f"\n{e}")
            return 4

    r = out.report
    card = r.scorecard
    print(f"\n{r.company_name}  {out.cin or ''}")
    score = "n/a" if card.overall is None else f"{card.overall}/10"
    print(f"Diligence Score {score}, confidence {card.confidence.value}, stage {r.stage.stage.value}")
    print(f"{len(r.flags)} flags ({sum(f.severity == 'red' for f in r.flags)} red), {len(r.evidence)} sources")
    print(f"AI cost for this report: ₹{out.cost_inr:.2f}")
    if out.log:
        print("\nNotes:")
        for line in out.log:
            print(f"  - {line}")

    slug = re.sub(r"[^a-z0-9]+", "-", r.company_name.lower()).strip("-") or "report"
    html_path = Path(args.out or f"{slug}.html")
    ctx = CheckContext(reputable_investors=frozenset(s.established_investors))
    variants = stage_variants(r.company_name, out.facts, ctx, out.narrative, r)
    html_path.write_text(render_html({slug: (r.company_name, variants)}), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(r.model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nSaved {html_path} (open in a browser) and {json_path}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    s = get_settings()
    if not s.data_gov_in_api_key:
        print("Set TRUECAP_DATA_GOV_IN_API_KEY first.")
        return 2
    url = f"https://api.data.gov.in/resource/{args.resource_id}"
    resp = httpx.get(url, params={"api-key": s.data_gov_in_api_key, "format": "json", "limit": "1"},
                     timeout=s.http_timeout_seconds)
    resp.raise_for_status()
    data = resp.json()
    print(f"Title: {data.get('title')}\nTotal records: {data.get('total')}")
    print("Fields:", ", ".join(f.get("id", "") for f in data.get("field", [])))
    if data.get("records"):
        print("First record:", json.dumps(data["records"][0], indent=1, ensure_ascii=False))
    return 0


def cmd_demo_html(args: argparse.Namespace) -> int:
    from truecap import sample_data
    from truecap.report import build_report

    companies = {}
    for key in ("kisankart", "struck_off", "sparse"):
        name, facts = getattr(sample_data, key)()
        r = build_report(name, facts, sample_data.sample_ctx())
        companies[key] = (name, stage_variants(name, facts, sample_data.sample_ctx(), None, r))
    path = Path(args.out or "sample-reports.html")
    path.write_text(render_html(companies, sample=True), encoding="utf-8")
    print(f"Saved {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="truecap")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("research", help="research a company and save the report")
    r.add_argument("name")
    r.add_argument("--city")
    r.add_argument("--website")
    r.add_argument("--cin")
    r.add_argument("--stage", choices=[s.value for s in Stage])
    r.add_argument("--out", help="HTML output path")
    r.set_defaults(fn=cmd_research)
    pr = sub.add_parser("probe-datagov", help="show the fields of a data.gov.in dataset")
    pr.add_argument("resource_id")
    pr.set_defaults(fn=cmd_probe)
    d = sub.add_parser("demo-html", help="render the fictional sample reports to HTML")
    d.add_argument("--out")
    d.set_defaults(fn=cmd_demo_html)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
