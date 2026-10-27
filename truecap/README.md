# TrueCap

Evidence-backed due diligence for angel investors, starting with Indian startups.
TrueCap checks a startup's public claims against public records and produces a private
report. **It is not investment advice**: it never says invest, buy or avoid.

## Status

| Stage | What | State |
|---|---|---|
| 1 | Domain model, evidence ledger, 24 checks, scoring engine, guards, DB models | ✅ done |
| 2a | Research pipeline: MCA data (data.gov.in), Claude web search with citations, company website, fact extraction with quote checks, CLI + HTML report | ✅ done |
| 2b | Job queue + worker, API, login, rate limits, DB-backed budget cap and cache | next |
| 3 | Frontend (Next.js, light/dark, mobile-first) | |
| 4 | Legal pages (drafts), founder right-of-reply + admin approval, deployment | |

## How scoring works

```
facts (each cites evidence) ──► 24 deterministic checks ──► pass / fail / unknown
                                                              │
                     category score = 10 × passed weight / (passed + failed weight)
                     overall        = stage-weighted mean of scored categories
                     confidence     = share of check weight that was decided
```

- **No LLM decides any number.** Checks are plain Python in `backend/truecap/checks/`.
- **Unknown never lowers the score**; it lowers confidence (Low / Medium / High).
- **Stage weights** are in `backend/truecap/scoring/weights.py` and are included in every report.
  The stage is inferred from funding rounds; the user can override it, and the report
  re-weights with no new research.
- **Every statement cites evidence.** The evidence ledger (claim, source, URL, date fetched,
  reliability) is stored per report, and the report can be rebuilt from it exactly.
- **Guards** (`backend/truecap/guards/`):
  - *Citations*: LLM sentences need valid `[E#]` markers, and their numbers must
    appear in the cited source, or the sentence is removed.
  - *Wording*: blocks advice ("invest", "avoid", "great investment"...) and
    accusations ("fraud", "fake", "misleading"...). House style: "Deck states X; filings show Y."
- **Verified / unverified**: a fact counts as verified when it comes from an official source,
  or from two independent sources on different domains.
- **Manual checks**: official portals that need a CAPTCHA (MCA, GST, IP India, eCourts) are
  never automated. The report links to them when the related check is unknown.

### The checks

| Category | Checks |
|---|---|
| Team | founders identified · background claims corroborated · prior startup/domain experience · director turnover · other directorships |
| Market | market-size claim sourced · recent independent coverage · well-funded competitors · regulatory licence |
| Traction | revenue claim vs filings · customer concentration · specific metrics · headcount trend · website live |
| Financials | filings up to date · funding independently reported · established investors · filed revenue trend |
| Legal | registry status Active · disqualified directors · litigation · GSTIN valid · trademark · founding year vs incorporation |

## Run it

```bash
cd truecap/backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q                      # tests (no network, no API keys)
.venv/bin/python -m truecap.demo                   # sample report for a fictional company
.venv/bin/python -m truecap.demo kisankart series_a  # same company, Series A weights
.venv/bin/python -m truecap.demo struck_off
.venv/bin/python -m truecap.demo sparse
```

## Research a real company (on your computer)

Real research needs internet access to data.gov.in, Anthropic's API and company websites.
Run it on your own machine (Python 3.11+):

```bash
cd truecap/backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env        # then open .env and fill in your keys (never commit .env)
.venv/bin/truecap research "Company name" --city Bengaluru
.venv/bin/truecap research "Company name" --website company.com --stage seed
```

It prints progress, then saves `company-name.html` (open it in a browser) and
`company-name.json`. If several companies match, it lists their CINs; run again with `--cin`.

**Keys**
- `TRUECAP_ANTHROPIC_API_KEY`: needed for web research, extraction and wording.
- `TRUECAP_DATA_GOV_IN_API_KEY` + `TRUECAP_DATA_GOV_IN_RESOURCE_IDS`: optional but recommended. These give
  official registry facts (status, incorporation date, paid-up capital, filings date). Register free at
  data.gov.in, open the "Company Master Data" dataset for the relevant state, and copy its resource id
  from the API tab. `truecap probe-datagov <resource_id>` shows the dataset's field names, so you can
  confirm TrueCap reads them correctly.

**What a run does**

1. Finds the company in MCA data, by CIN or exact name. Falls back to a short web search for CIN candidates.
2. Asks Claude (Sonnet 5.5, up to 8 web searches) for cited findings on founders, funding, filed revenue,
   legal matters, market and coverage. Sentences without a citation are dropped. Only the
   verbatim cited snippet counts as source text.
3. Fetches up to 4 public pages of the company's site (respects robots.txt, skips login pages) and
   finds a GSTIN if one is printed.
4. Claude (Haiku 5.5) extracts structured facts. **Each fact's quote must appear word-for-word in the
   cited source, or it is dropped.** Code then applies reliability rules. For example, a "filed" figure that only the
   company reports is treated as a company claim, and a funding round counts as independently reported only
   if a non-company source reports it.
5. Runs the 24 checks, scores the report, and has Claude write pros and cons. That text still passes both guards.

Expected AI cost is about ₹12–25 per fresh report. The run prints the actual cost.
The monthly cap is enforced per run in the CLI. Tracking it across runs arrives with the database-backed API in Stage 2b.
