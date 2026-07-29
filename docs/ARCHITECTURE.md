# Architecture

> Technical architecture and contribution guidelines for Championship Squad Tracker.

---

## System Layout

The system is organised into four distinct layers. Each layer has a single responsibility and communicates with adjacent layers through well-defined typed interfaces.

```
┌─────────────────────────────────────────────────────────┐
│                    Dashboard UI                         │
│              (Visualisation & Reporting)                │
├─────────────────────────────────────────────────────────┤
│                  Storage Layer                          │
│         (Structured JSON File System)                   │
│   data/raw/*.json  →  data/processed/*.json             │
├─────────────────────────────────────────────────────────┤
│              Processing & Normalisation                 │
│   ┌──────────────────┐  ┌───────────────────────────┐   │
│   │ filter_relevant_ │  │ calculate_squad_vacuum()  │   │
│   │ players()        │  │                           │   │
│   └──────────────────┘  └───────────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│                  Pydantic v2 Models                     │
│   Player │ Transfer │ PlayerStats │ MedicalHistory │    │
│   Club   │ SquadVacuumResult                            │
├─────────────────────────────────────────────────────────┤
│                  Collectors Layer                       │
│   ┌─────────────┐ ┌──────────────┐ ┌────────────────┐  │
│   │  Transfer    │ │   Stats      │ │   Medical      │  │
│   │  Collector   │ │   Collector  │ │   Collector    │  │
│   └──────┬──────┘ └──────┬───────┘ └───────┬────────┘  │
│          │               │                 │            │
│          └───────────────┼─────────────────┘            │
│                          │                              │
│              BaseDataProvider (pluggable)                │
│          MockDataProvider │ LiveDataProvider             │
└─────────────────────────────────────────────────────────┘
```

### Layer Responsibilities

| Layer | Module Path | Responsibility |
|---|---|---|
| **Collectors** | `src/collectors/` | Fetch raw data from pluggable data providers. No transformation logic. |
| **Models** | `src/models/` | Define and validate all data schemas using Pydantic v2. Single source of truth for types. |
| **Processing** | `src/processing/` | Filter, aggregate, and derive metrics from validated models. |
| **Storage** | `src/storage/` | Persist validated and processed data as structured local JSON files. |
| **Pipeline** | `src/pipeline.py` | Orchestrate the full ingestion flow: collect → validate → process → store. |

---

## Contribution Rules

### 1. Strict Determinism Policy

> **All code in `src/collectors/` and `src/processing/` MUST be strictly deterministic.**

This means:
- **No LLM, AI, or probabilistic logic** in data collection or processing modules.
- **No randomness**: Do not use `random`, `uuid4()`, or any non-deterministic identifiers unless seeded and reproducible.
- **Same input → same output**: Given identical source data, the pipeline must produce byte-identical JSON output across runs.
- **No network calls in tests**: All unit tests must use mock data providers. No live HTTP requests during `pytest`.

### 2. Type Safety Guidelines

- All data structures **must** be defined as Pydantic v2 `BaseModel` subclasses.
- Use Python `Enum` for categorical fields (`TransferDirection`, `TransferType`).
- All function signatures **must** include full type annotations (parameters and return types).
- Enable `strict=True` mode on Pydantic models where appropriate to prevent implicit coercion.
- Run `mypy` or `pyright` as part of the development workflow.

### 3. Data Flow Principles

```
Data Sources
    ↓
Collectors (raw fetch, no transformation)
    ↓
Pydantic Validation (type checking, constraint enforcement)
    ↓
Processing (filtering, aggregation, metric calculation)
    ↓
Raw JSON Storage (data/raw/)
    ↓
Processed JSON Storage (data/processed/)
    ↓
Dashboard UI (read-only consumption)
```

**Rules**:
- Collectors **never** write directly to storage. They return validated model instances.
- Processing functions accept and return typed model instances, never raw dicts.
- The storage layer serialises models using Pydantic's `.model_dump_json()` for consistency.
- The Dashboard UI is a **read-only consumer** — it never mutates stored data.

### 4. Module Boundaries

- `models/` has **zero** imports from other `src/` modules.
- `collectors/` imports only from `models/`.
- `processing/` imports only from `models/`.
- `storage/` imports from `models/` only.
- `pipeline.py` is the sole orchestrator that wires collectors, processing, and storage together.

### 5. Testing Standards

- Every public function must have corresponding unit tests.
- Use `pytest` as the test runner.
- Mock all external data sources using `BaseDataProvider` implementations.
- Target **≥ 90% code coverage** on `src/` modules.

---

## File Naming Conventions

| Type | Convention | Example |
|---|---|---|
| Python modules | `snake_case.py` | `transfer.py`, `json_store.py` |
| Test files | `test_<module>.py` | `test_models.py` |
| JSON data files | `<entity>_<club_id>.json` | `transfers_luton.json` |
| Documentation | `UPPER_CASE.md` | `ARCHITECTURE.md` |
