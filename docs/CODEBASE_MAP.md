# Codebase Map (AST Index)
> **Note for AI Agents:** Do NOT run `grep` or `glob` across the codebase.> Consult this file first to identify relevant paths, classes, and method signatures.
**Source Directory:** `src/`  

---
### `src/cli.py`
  > *cli.py*
  - `def _build_parser()`
  - `def run_analyze(club_id, use_mock, output)`
  - `def main(argv)`

### `src/collectors/__init__.py`
  > *src/collectors — deterministic data-collection modules.*

### `src/collectors/base.py`
  > *base.py*
  - `class CollectorError`
  - `class NetworkError`
    - `def __init__(self, message, url, status)`
    - `def __str__(self)`
  - `class ParseError`
    - `def __init__(self, message, field, raw)`
    - `def __str__(self)`
  - `class BaseCollector`
    - `def __init__(self, timeout)`
    - `def fetch_data(self, club_id)`
    - `def timeout(self)`
    - `def __repr__(self)`

### `src/collectors/manager.py`
  > *manager.py*
  - `class ManagerClubCollector`
    - `def __init__(self, mock_path, timeout)`
    - `def _load_clubs(self)`
    - `def fetch_data(self, club_id)`
    - `def fetch_club_context(self, club_id)`

### `src/collectors/medical.py`
  > *medical.py*
  - `class MedicalCollector`
    - `def __init__(self, mock_path, timeout)`
    - `def _load_records(self)`
    - `def _parse_records(self, raw_records)`
    - `def fetch_data(self, club_id)`
    - `def fetch_medical_history(self, player_id)`

### `src/collectors/stats.py`
  > *stats.py*
  - `def _safe_int(raw)`
  - `def _safe_float(raw)`
  - `def _ppg_to_rating(ppg)`
  - `def _current_season_start_year(today)`
  - `def _last_two_season_years(today)`
  - `def _season_label(year)`
  - `def _parse_row(row, season_label)`
  - `def _parse_season_page(html, season_label)`
  - `class StatsCollector`
    - `def __init__(self, club_id, season_years, timeout, mock_file)`
    - `def _load_mock_stats(self)`
    - `def fetch_data(self, club_id)`
    - `def fetch_player_stats(self, player_id)`
    - `def _resolve_club(club_id)`
    - `def _build_url(self, numeric_id, slug, year)`
    - `def _get_html(self, url)`
    - `def __repr__(self)`

### `src/collectors/transfers.py`
  > *transfers.py*
  - `def _parse_fee(raw)`
  - `def _season_label(year)`
  - `def _parse_row(row, direction, club_name, season_year)`
  - `def _scrape_transfers_page(html, club_name, season_year)`
  - `class TransferCollector`
    - `def __init__(self, season_year, timeout, polite_delay, mock_file)`
    - `def _load_mock_transfers(self)`
    - `def fetch_data(self, club_id)`
    - `def _resolve_club(self, club_id)`
    - `def _build_url(self, numeric_id, slug)`
    - `def _get_html(self, url)`
    - `def _extract_club_name(html)`
    - `def __repr__(self)`

### `src/pipeline.py`
  > *pipeline.py*
  - `class EFLDataPipeline`
    - `def __init__(self, manager_collector, transfer_collector, stats_collector, medical_collector, use_mock)`
    - `def run_club_pipeline(self, club_id)`
    - `def _build_squad_stats_summary(club, player_stats)`
    - `def _calculate_injury_risk_score(club, medical_records)`
    - `def _calculate_transfer_balance(transfers)`

### `src/processors/squad_processor.py`
  > *squad_processor.py*
  - `def filter_relevant_transfers(transfers, player_stats, min_minutes)`
  - `def calculate_squad_vacuum(transfers_out, player_stats)`

### `src/reporter.py`
  > *reporter.py*
  - `class ClubReporter`
    - `def __init__(self, console)`
    - `def print_terminal_summary(self, ranking)`
    - `def export_markdown_report(self, ranking, output_path)`

### `src/schemas.py`
  > *schemas.py*
  - `class TransferDirection`
  - `class TransferType`
  - `class Player`
  - `class Transfer`
    - `def _fee_consistency(self)`
  - `class PlayerStats`
    - `def _validate_season_format(cls, value)`
  - `class MedicalRecord`
  - `class Club`
    - `def _transfers_direction_consistency(self)`
  - `class SquadVacuumResult`
  - `class SquadStatsSummary`
  - `class ClubAnalysisReport`
  - `class FinalClubRanking`

### `src/scoring/__init__.py`
  > *src/scoring — post-pipeline analysis scorers operating on ClubAnalysisReport.*

### `src/scoring/financial_scorer.py`
  > *financial_scorer.py*
  - `class FinancialScorer`
    - `def calculate_score(self, report)`
    - `def _psr_risk_score(net_spend, squad_value)`
    - `def _net_spend_score(net_spend, squad_value)`
    - `def _budget_efficiency_score(total_output, squad_value)`
  - `def _clamp(value, low, high)`

### `src/scoring/injury_scorer.py`
  > *injury_scorer.py*
  - `class InjuryScorer`
    - `def calculate_score(self, report)`

### `src/scoring/matrix_engine.py`
  > *matrix_engine.py*
  - `class MatrixEngine`
    - `def __init__(self, injury_weight, financial_weight, tactical_weight)`
    - `def evaluate_club(self, report)`
  - `def _clamp(value, low, high)`

### `src/scoring/tactical_scorer.py`
  > *tactical_scorer.py*
  - `class TacticalScorer`
    - `def calculate_score(self, report)`
    - `def _manager_tenure_score(tenure_years)`
    - `def _squad_age_score(average_age)`
    - `def _performance_trend_score(trend)`
  - `def _clamp(value, low, high)`

