# League Runner Operations Guide

This guide covers running analysis across an entire league, how `CacheManager` avoids redundant collection, and the report formats produced.

---

## Overview

`LeaguePipeline` (`src/league_pipeline.py`) drives a full league run:

1. Resolve the set of club IDs for the given `league_id` / `season`.
2. For each club, either load a cached `ClubAnalysisReport` or run `EFLDataPipeline.run_club_pipeline` fresh.
3. Score every club with `MatrixEngine.evaluate_club`.
4. Assemble a `LeagueAnalysisReport` with per-club `LeagueClubStanding` entries (rank, score, percentile).

Invoke it via the CLI:

```bash
python -m src.cli analyze-league --league championship --season 2026-2027
```

---

## CacheManager Architecture

`CacheManager` (`src/cache.py`) is a namespaced, file-backed JSON cache, scoped to a single `(league, season)` pair.

**File layout**:

```
data/cache/{league}/{season}/{key}.json
```

For example, a cached club report for Leeds United in the 2026-2027 Championship season would live at:

```
data/cache/championship/2026-2027/c_399.json
```

**Envelope format** — each file stores the payload alongside a write timestamp:

```json
{
  "cached_at": 1732980000.0,
  "data": { "...": "club analysis report fields" }
}
```

**API**:

| Method | Behavior |
|---|---|
| `get(key)` | Returns the cached `data` dict, or `None` if no file exists for `key`. |
| `set(key, data)` | Writes `data` to `{key}.json`, stamped with the current time. |
| `is_expired(key, ttl_hours=168)` | Returns `True` if there's no cached entry, or the entry's age exceeds `ttl_hours` (default: 7 days). |

`LeaguePipeline._load_report` consults `is_expired` before deciding whether to reuse a cached club report or re-run the collectors for that club.

### `--force-refresh`

The `analyze-league` CLI subcommand exposes a `--force-refresh` flag, which maps to `use_cache=False`:

```bash
python -m src.cli analyze-league --league championship --season 2026-2027 --force-refresh
```

When set, every club in the league is re-collected from scratch, bypassing `CacheManager.get` / `is_expired` entirely, regardless of TTL. Use this after a known data correction upstream, or when refreshing stale fixtures ahead of a new reporting cycle.

Without the flag (the default), the pipeline trusts any cache entry younger than the TTL and only re-collects clubs whose entries are missing or expired — keeping league-wide runs fast for large, repeated analyses.

---

## Delta Updates vs. Full Scrapes

- **Delta update** (default, cache-enabled run): only clubs with missing or expired (`is_expired` → `True`) cache entries are re-collected. This is the normal mode for re-running a league mid-season, since most clubs' transfer/stats/medical data won't change hour-to-hour.
- **Full scrape** (`--force-refresh`): every club is re-collected regardless of cache state. Reserve this for season rollovers — a new `season` value produces a new cache namespace (`data/cache/{league}/{new-season}/`) anyway, so a full scrape is effectively automatic the first time a new season is run, since there's no prior cache to hit.

In practice, when moving to a new season for the first time, no `--force-refresh` is needed — the pipeline naturally performs a full scrape because the cache directory for that season doesn't exist yet. `--force-refresh` matters when re-running an *existing* season/league combination and you need to discard already-cached data.

---

## Output Formats

### Terminal (League Table)

`run_analyze_league` prints a plain ranked table directly to stdout:

```
League Table: championship 2026-2027

Rank  Club                        Score     Percentile
------------------------------------------------------
1     Leeds United                 87.40      98.50
2     Sunderland                    82.10      91.20
...
```

### Terminal (Single Club — Rich)

`ClubReporter.print_terminal_summary` (`src/reporter.py`) renders a Rich-formatted panel for a single `FinalClubRanking`:

- Header line with club ID and overall score (`X.XX / 100`).
- A `Category Breakdown` table with columns: **Category**, **Raw Score**, **Weighted Contribution**.

### Markdown Report

`ClubReporter.export_markdown_report` writes a Markdown file for a single club:

```markdown
# Club Analysis Report — c_399

_Generated 2026-07-30 14:00 UTC_

**Overall Score:** 87.40 / 100

## Category Breakdown

| Category | Raw Score | Weighted Contribution |
|---|---|---|
| Financial | 84.20 | 25.26 |
| Injury    | 91.00 | 27.30 |
| Tactical  | 86.50 | 25.95 |
```

If `--output` is a directory (or omitted with a default), the file is written to `<output>/<club_id>_report.md`; if it ends in `.md`, that exact path is used.

League runs currently emit the terminal table only — per-club Markdown export can still be produced by running `analyze --club-id <id> --output <path>` for any club of interest after a league pass.
