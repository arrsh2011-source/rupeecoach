# TrueCap

Evidence-backed due diligence for angel investors, starting with Indian startups.
TrueCap checks a startup's public claims against public records and produces a private
report. **It is not investment advice**: it never says invest, buy or avoid.

## Status

| Stage | What | State |
|---|---|---|
| 1 | Domain model, evidence ledger, 24 checks, scoring engine, guards, DB models | ✅ done |
| 2 | Research pipeline (data.gov.in, web search via Claude, website), job queue, API, auth, rate limits, budget cap | next |
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
