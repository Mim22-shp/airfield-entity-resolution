# 🛩️ Airfield Entity Resolution System (India)
### Scalable Geospatial Record Linkage, Graph-Based Clustering, & Operational Auditability

[![Python](https://img.shields.io/badge/Python-3.13+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791.svg?style=flat&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![PostGIS](https://img.shields.io/badge/PostGIS-Spatial%20Engine-006400.svg?style=flat&logo=postgis&logoColor=white)](https://postgis.net/)
[![NetworkX](https://img.shields.io/badge/NetworkX-Graph%20Clustering-orange.svg?style=flat)](https://networkx.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B.svg?style=flat&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![FastAPI](https://img.shields.io/badge/FastAPI-REST%20API-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Pytest](https://img.shields.io/badge/Pytest-13%20Passed-0A9EDC.svg?style=flat&logo=pytest&logoColor=white)](https://pytest.org/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?style=flat&logo=docker&logoColor=white)](https://www.docker.com/)
[![RapidFuzz](https://img.shields.io/badge/RapidFuzz-String%20Matching-blueviolet.svg?style=flat)](https://github.com/maxbachmann/RapidFuzz)

---

## 📋 Executive Summary

The **Airfield Entity Resolution System** is an enterprise-grade geospatial entity resolution and deduplication pipeline designed to link, reconcile, and resolve fragmented airfield records across multiple heterogeneous data sources—**OurAirports**, **OpenStreetMap (OSM)**, and **Wikidata**—into a single canonical master dataset of Indian airfields.

Unlike naive fuzzy-matching scripts, this system combines:
1. **High-Performance Spatial Blocking in PostGIS** to bypass $O(N^2)$ Cartesian explosion.
2. **Multi-Feature Evidence Scoring** using calibrated geometric distance decay, token-level fuzzy string metrics, verified aeronautical identifiers (ICAO/IATA), and classification hierarchies.
3. **Graph-Theoretic Cluster Resolution (NetworkX)** to extract connected components and generate deterministic, immutable master entity UUIDs.
4. **Operational Conflict Guardrails** that actively flag spatial dispersion anomalies, code contradictions, and multi-entity ambiguities.
5. **Full Explainability & Audit Trail (`why_linked`)** implemented directly in PostgreSQL/PostGIS, allowing stakeholders to query the exact mathematical evidence behind any merge decision.
6. **Interactive Visual Dashboard** powered by **Streamlit** and **PyVis**, providing real-time spatial filtering, audit drill-downs, and interactive force-directed graph exploration.
7. **REST Explainability Microservice (FastAPI)** delivering high-speed `/entity/{id}/why` JSON evidence payloads and plain-text operational audit reports with automated **pytest** coverage and **Docker** containerization.

---

## 🏛️ System Architecture & Data Pipeline

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 1: RAW INGESTION (Immutable Provenance Foundation)                         │
│  - OurAirports CSV (HTTP)  |  OSM Overpass API (JSON)  |  Wikidata SPARQL (JSON) │
│  - Tagged with unique source_id, load_timestamp; PostGIS GIST spatial indices     │
│  - Storage: raw_ourairports, raw_osm, raw_wikidata                               │
└─────────────────────────────────────────┬────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 2: NORMALIZATION VIEW (PostGIS SQL)                                        │
│  - Text sanitization: Lowercasing, facility stop-word stripping (AFS, civil, etc)│
│  - Standardized taxonomy: commercial, general_aviation, helipad, military, other │
│  - Reprojection to India Metric CRS (EPSG:7755) + WGS84 coordinates (EPSG:4326)  │
│  - View: normalized_airfields                                                    │
└─────────────────────────────────────────┬────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 3: CANDIDATE GENERATION / BLOCKING (PostGIS)                               │
│  - Pairs constrained by: ST_DWithin(geom_metric, 10000) OR ICAO/IATA code match   │
│  - Asymmetry filter: a.source_id < b.source_id (avoids duplicate/self pairs)     │
│  - Table: candidate_pairs (indexed on pair_id, id_a, id_b, distance_m)           │
└─────────────────────────────────────────┬────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 4: MULTI-FEATURE SCORING & AUDIT EVIDENCE                                  │
│  - RapidFuzz token matching (35%) + Spatial Distance decay (30%)                 │
│  - ICAO/IATA Code Verification (20%) + Facility Type Compatibility (15%)         │
│  - Calibrated Bands: auto-merge (>= 0.80), human-review (0.50-0.79), non-match   │
│  - Table: match_evidence (features, weights, ruleset_version, narrative reasons)  │
└─────────────────────────────────────────┬────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 5: GRAPH RESOLUTION & CONFLICT DETECTION                                   │
│  - NetworkX Graph: Nodes = Sources, Edges = Confidence-weighted auto-merges      │
│  - Connected Components -> Master Entities (Deterministic UUIDv5)                │
│  - Conflict Guardrails: Spread > 5km, Code conflicts, Ambiguous cross-links      │
│  - Tables: resolved_entities, entity_summary, resolution_conflicts               │
│  - Export: airfield_graph.html (Interactive force-directed PyVis network)        │
└─────────────────────────────────────────┬────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 6: AUDIT TRAIL & OPERATIONAL SCRUTINY                                      │
│  - PostgreSQL Functions: why_linked(target_id) & why_linked_summary(target_id)    │
│  - Plain-English operational audit reports and tabular feature decision matrix   │
└─────────────────────────────────────────┬────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 7: EXPORTS & STREAMLIT DASHBOARD                                           │
│  - GIS Exports: resolved_airfields.geojson & resolved_airfields_map.csv          │
│  - Web App: Spatial Distribution, NetworkX Graph Visualizer, Conflict Auditing    │
└─────────────────────────────────────────┬────────────────────────────────────────┘
                                          │
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│ STAGE 8: FASTAPI EXPLAINABILITY SERVICE & DOCKER DEPLOYMENT                      │
│  - REST Endpoints: /entity/{id}/why (JSON breakdown & text), /entity/{id}, /health│
│  - Full Automated Pytest Suite: 13 tests covering endpoints & scoring units      │
│  - Production Dockerfile & docker-compose.yml (PostGIS + FastAPI orchestration)  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔬 Multi-Feature Scoring Methodology

Candidate pairs generated during blocking are evaluated across four orthogonal feature dimensions, producing a normalized confidence score:

$$\text{Confidence} = w_{\text{name}} \cdot S_{\text{name}} + w_{\text{dist}} \cdot S_{\text{dist}} + w_{\text{code}} \cdot S_{\text{code}} + w_{\text{type}} \cdot S_{\text{type}}$$

| Feature | Weight ($w_i$) | Evaluation Logic | Rationale |
|---|---|---|---|
| **Name Similarity** ($S_{\text{name}}$) | **0.35** | $\max(\text{token\_set\_ratio}, \text{token\_sort\_ratio}) / 100$ on regex-cleaned names | Handles reordered terms, administrative prefixes, and missing facility qualifiers. |
| **Spatial Proximity** ($S_{\text{dist}}$) | **0.30** | Linear metric decay: $\max\left(0, 1.0 - \frac{\text{distance\_m}}{10000}\right)$ in EPSG:7755 | Enforces strict geographic bounds; co-located records score near 1.0; $>10\text{ km} \rightarrow 0.0$. |
| **Code Verification** ($S_{\text{code}}$) | **0.20** | Verified agreement = `1.0`, Conflict = `0.0`, Neutral (missing) = `0.5` | ICAO/IATA codes are high-value ground truth when present; missing codes do not penalize. |
| **Type Compatibility** ($S_{\text{type}}$) | **0.15** | Cross-classification matrix (Commercial, GA, Military, Helipad, Closed) | Prevents merging disparate physical infrastructures (e.g. standalone helipads with international airports). |

### Decision Threshold Bands
- **`auto-merge` ($\ge 0.80$):** High-confidence linkage. Edge added to the NetworkX resolution graph.
- **`human-review` ($0.50 \le \text{score} < 0.80$):** Borderline linkage. Logged for manual inspection; used to detect multi-entity ambiguity conflicts.
- **`non-match` ($< 0.50$):** Rejected candidate pair.

---

## 🛡️ Operational Conflict Detection Guardrails

Entity resolution engines that naively merge records can cause catastrophic data corruption (e.g., transitively chaining airports 50 km apart). This pipeline incorporates automated guardrails:

1. **Coordinate Spread Conflict (`COORDINATE_CONFLICT`):** Flagged if the pairwise maximum great-circle distance between any two merged points in an entity exceeds **5,000 meters**.
2. **Identifier Conflict (`CODE_CONFLICT`):** Flagged if an entity contains multiple distinct, non-null ICAO or IATA codes.
3. **Type Incompatibility (`TYPE_CONFLICT`):** Flagged if an entity merges incompatible facility types (e.g., `commercial` and `helipad`).
4. **Ambiguous Borderline Link (`AMBIGUOUS_LINK_CONFLICT`):** Flagged when a record belonging to Entity A has a borderline candidate match ($\ge 0.55$ confidence) linking to Entity B.

All conflicts are written to `resolution_conflicts` with severity ratings (`HIGH`, `MEDIUM`) and detailed explanatory narratives.

---

## 📂 Project Structure

```
.
├── airfield_env/                  # Python virtual environment (dependencies)
├── .vscode/
│   └── settings.json              # VS Code & Pylance interpreter binding
├── ingest.py                      # Stage 1: Ingest OurAirports, OSM, & Wikidata
├── normalize.py                   # Stage 2: Create normalized_airfields PostGIS view
├── blocking.py                    # Stage 3: Generate candidate pairs via ST_DWithin & codes
├── scoring.py                     # Stage 4: 4-feature weighted scoring engine & evidence logging
├── entity_resolution.py           # Stage 5: NetworkX graph clustering & conflict detection
├── audit.py                       # Stage 6: PostGIS stored functions & CLI audit runner
├── export_data.py                 # Stage 7a: Export resolved entities to GeoJSON
├── export_map.py                  # Stage 7b: Export source points to CSV for mapping
├── run_pipeline.py                # Master CLI: Orchestrates Stages 1-7 end-to-end
├── dashboard.py                   # Streamlit web application with embedded NetworkX graphs
├── api.py                         # Stage 8: FastAPI REST Service & /entity/{id}/why explainability
├── Dockerfile                     # Multi-stage production container image
├── .dockerignore                  # Docker build exclusion definitions
├── docker-compose.yml             # Orchestration: PostGIS Database + FastAPI Service
├── tests/                         # Pytest test suite (13 automated tests)
│   ├── __init__.py                # Test package marker
│   ├── conftest.py                # Test fixtures, TestClient, & mock DB connection
│   ├── test_api.py                # End-to-end API tests for all endpoints
│   └── test_scoring.py            # Unit tests for scoring, distance, and token matching
├── airfield_graph.html            # Standalone interactive PyVis force-directed network graph
├── resolved_airfields.geojson     # Output: GeoJSON of canonical master airfields
├── resolved_airfields_map.csv     # Output: Flattened CSV of resolved records with UUIDs
└── README.md                      # Comprehensive system documentation
```

---

## 🗄️ Database Schema & Data Dictionary

| Table / View | Type | Primary Key | Description |
|---|---|---|---|
| `raw_ourairports` | Table | `source_id` | Immutable raw records ingested from OurAirports CSV. |
| `raw_osm` | Table | `source_id` | Immutable raw records ingested from OpenStreetMap Overpass API. |
| `raw_wikidata` | Table | `source_id` | Immutable raw records ingested from Wikidata SPARQL endpoint. |
| `normalized_airfields` | View | `source_id` | Unified schema with cleaned names, standardized types, and EPSG:7755 geometries. |
| `candidate_pairs` | Table | `pair_id` | Spatially blocked candidate pairs ($< 10\text{ km}$ or code match). |
| `match_evidence` | Table | `(id_a, id_b)` | Complete audit trail of pairwise scores, weights, bands, and decision narratives. |
| `resolved_entities` | Table | `source_id` | Mapping of every individual source record to its resolved `entity_id` (UUIDv5). |
| `entity_summary` | Table | `entity_id` | Canonical rollup per master entity with centroids, name priority, and conflict flags. |
| `resolution_conflicts` | Table | Composite | Operational log of all flagged anomalies with severity and involved records. |

---

## 🚀 Installation & Setup

### Prerequisites
- **Python 3.10+** (Tested on Python 3.13)
- **PostgreSQL 14+** with the **PostGIS** extension enabled
- PostGIS database connection URL (e.g., `postgresql://postgres:password@localhost:5432/airfields`)

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/airfield-entity-resolution.git
cd airfield-entity-resolution
```

### 2. Configure Virtual Environment & Dependencies
```powershell
# Create virtual environment
python -m venv airfield_env

# Activate virtual environment
.\airfield_env\Scripts\Activate.ps1

# Install required dependencies
pip install -r requirements.txt
```

*(Key libraries: `geopandas`, `sqlalchemy`, `psycopg2-binary`, `networkx`, `pyvis`, `rapidfuzz`, `streamlit`, `shapely`, `requests`)*

### 3. Configure Database URL
Copy .env.example to .env and add your password.

Set the environment variable `AIRFIELDS_DB_URL` (or update default connection strings in scripts):
```powershell
$env:AIRFIELDS_DB_URL="postgresql://postgres:your_password@localhost:5432/airfields"
```

Ensure PostGIS is activated in your PostgreSQL database:
```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

---

## 💻 Execution & Usage

### 1. Run Complete Pipeline (End-to-End)

To run all 7 stages—from fresh data ingestion to GIS export and graph generation:
```powershell
.\airfield_env\Scripts\python.exe run_pipeline.py
```

To re-run the pipeline rapidly using existing PostGIS raw tables (skips network download):
```powershell
.\airfield_env\Scripts\python.exe run_pipeline.py --skip-fetch
```

---

### 2. Operational Audit CLI: `audit.py`

Inspect any resolved entity and review the complete mathematical justification for its merges:

```powershell
# Audit by Master Entity UUID:
.\airfield_env\Scripts\python.exe audit.py 1475752c-e1fc-583b-967b-1cb11f26a1ca

# Or audit by any source record ID (e.g. from OurAirports or OSM):
.\airfield_env\Scripts\python.exe audit.py ourairports_26629
```

**Direct SQL Query:**
```sql
-- Tabular feature breakdown:
SELECT id_a, name_a, id_b, name_b, distance_m, name_sim_score, code_match_score, final_confidence, band, reason_narrative
FROM why_linked('1475752c-e1fc-583b-967b-1cb11f26a1ca');

-- Executive text narrative:
SELECT why_linked_summary('1475752c-e1fc-583b-967b-1cb11f26a1ca');
```

---

### 3. Launch the Streamlit Dashboard

Start the interactive web dashboard:
```powershell
.\airfield_env\Scripts\streamlit.exe run dashboard.py
```
#### Streamlit Dashboard Link: https://airfield-entity-resolution-mvjtk85tvrjcmhhtcbnqdr.streamlit.app/

#### Dashboard Features:
- **🗺️ Spatial Distribution & Filter:** Interactive map of Indian airfields with type, source, and cluster status filtering.
- **🕸️ NetworkX Graph Visualizer:**
  - *Single Entity Subgraph:* Draggable, zoomable force-directed network showing member nodes, confidence-weighted edges, and metadata cards.
  - *Global Merged Network:* Full-scale interactive PyVis visualization of all cluster merges across India.
- **⚠️ Conflict Inspection:** Real-time view of entities flagged by guardrails with direct descriptions of detected anomalies.
- **🔍 'Why Linked?' Audit Explorer:** Full interactive audit trail answering *"Why did you merge these records?"* with tabular metrics and graph visualizer.
- **📋 Raw Mappings:** Live paginated view of individual source-to-master entity mappings.

---

### 4. FastAPI Explainability REST Service: `api.py`

A production-grade REST microservice providing programmatic explainability, search, and health monitoring for downstream services and intelligence platforms.

#### Start the API Server:
```powershell
.\airfield_env\Scripts\python.exe -m uvicorn api:app --reload --host 0.0.0.0 --port 8000
```
- **Interactive Swagger UI:** Open [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation:** Open [http://localhost:8000/redoc](http://localhost:8000/redoc)

#### Core Endpoints:
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health status and live PostGIS database connectivity check. |
| `GET` | `/entities` | Paginated search across resolved master airfields (supports `search`, `limit`, `offset`, `has_conflict`). |
| `GET` | `/entity/{id}` | Canonical metadata rollup for a master entity or source record ID. |
| `GET` | `/entity/{id}/why` | **Operational Explainability:** Complete mathematical evidence, component weights, pairwise match scores, constituent records, and narrative justifications behind why records were merged into this entity. |

#### Querying `/entity/{id}/why`:
The endpoint accepts either a master `entity_id` (UUID) or any constituent raw source record ID (e.g. `osm_747078123`, `ourairports_42716`):

```powershell
# 1. Query by Master Entity UUID (Structured JSON)
curl.exe http://localhost:8000/entity/027aa6b9-6155-51fd-b5bc-4ea6925156df/why

# 2. Query by raw source ID (Automatically resolves to master entity)
curl.exe http://localhost:8000/entity/osm_747078123/why

# 3. Formatted ASCII Operational Audit Report (Plain Text)
curl.exe "http://localhost:8000/entity/027aa6b9-6155-51fd-b5bc-4ea6925156df/why?format=text"

# 4. Using PowerShell's built-in JSON parser:
Invoke-RestMethod http://localhost:8000/entity/027aa6b9-6155-51fd-b5bc-4ea6925156df/why
```

---

### 5. Automated Testing with Pytest

The test suite covers API endpoints, input validation, singleton handling, 404 error responses, as well as core mathematical scoring unit logic:

```powershell
# Run the complete test suite
.\airfield_env\Scripts\python.exe -m pytest -v
```

**Test Coverage Summary (13 tests):**
- `tests/test_api.py`: Root `/`, `/health`, `/entity/{id}/why` (JSON), source ID resolution, `?format=text` report, singleton explanation, and 404 handling.
- `tests/test_scoring.py`: Linear distance metric decay, ICAO/IATA code verification (agreement, conflict, neutrality), facility type matrix compatibility, RapidFuzz token matching, and Haversine distance calculations.

---

### 6. Containerized Deployment (Docker & Docker Compose)

#### Option A: Docker Compose (Full Stack: PostGIS + FastAPI)
Spins up a PostGIS database and the FastAPI service together with automated health checks:
```bash
docker compose up -d --build
```
Access the API at `http://localhost:8000/docs`.

#### Option B: Standalone Docker Image
```bash
# Build the Docker image
docker build -t airfield-entity-api .

# Run the container
docker run -d --name airfield-api \
  -p 8000:8000 \
  -e AIRFIELDS_DB_URL="postgresql://postgres:password@host.docker.internal:5432/airfields" \
  airfield-entity-api
```

---

## 📊 Key Results & Metrics

All metrics below are computed directly from the end-to-end pipeline execution and verified against the PostGIS database and exported artifacts (`resolved_airfields.geojson` and `resolved_airfields_map.csv`):

| Metric | Verified Empirical Value | Detailed Breakdown |
|---|---|---|
| **Raw Airfield Records Ingested** | **1,610** records | • **OurAirports:** 661<br>• **OpenStreetMap (OSM):** 570<br>• **Wikidata:** 379 |
| **Resolved Canonical Airfields** | **1,018** Master Entities | • **Multi-record clusters:** 347 entities (34.1%)<br>• **Singletons:** 671 entities (65.9%) |
| **Multi-Source Deduplicated Merges** | **347** Entities resolved across $\ge 2$ sources | • **All 3 sources (OSM + OurAirports + Wikidata):** 215<br>• **2 sources:** 107 (OSM + OurAirports: 61, OurAirports + Wikidata: 26, OSM + Wikidata: 20)<br>*(347 entities total contain $> 1$ record, including intra-source merges)* |
| **Candidate Blocking Reduction** | **99.86%** reduction vs. $O(N^2)$ Cartesian explosion | • **Total possible pairs:** $1,295,245$ $\left(\frac{1610 \times 1609}{2}\right)$<br>• **Candidate pairs evaluated:** 1,752 (1,141 spatial 10km, 607 spatial & code, 4 code-only)<br>• **Eliminated:** 1,293,493 pairs ($99.865\%$) |
| **Operational Guardrail Flagging Rate** | **12.1%** flagged for review (123 of 1,018 entities) | • **Clean merges:** 895 entities (87.9%)<br>• **Flagged for human review:** 123 entities (12.1%) with 214 total anomaly signals logged |

### 🛡️ Operational Guardrail Flagging Breakdown (123 Flagged Entities)

With strict ICAO 4-letter validation (`^[A-Z]{4}$`) and resolution ambiguity checks focused on multi-record merged clusters, the guardrails flag real operational edge cases while achieving **87.9% clean merges**:

| Conflict Type | Severity | Logged Count | Root Cause & Operational Rationale |
|---|---|---|---|
| **`AMBIGUOUS_LINK_CONFLICT`** | MEDIUM | **150** | A member record in a merged cluster has a candidate review link ($\text{confidence} \ge 0.55$) to another entity (e.g. adjacent facilities or alternate plausible links within 10 km). Surfaces potential over-clustering for human inspection. |
| **`CODE_CONFLICT`** | HIGH / MEDIUM | **62** (43 ICAO, 19 IATA) | Multiple distinct verified aeronautical codes within a single cluster (e.g., joint civil enclave vs. IAF military base codes, or differing authoritative identifiers across sources). |
| **`COORDINATE_CONFLICT`** | HIGH | **2** | Merged source points span $> 5,000\text{ m}$ apart. Flags physical coordinate dispersion across heterogeneous sources. |

---

## 📜 License & Acknowledgments

- **License:** MIT License. Free for academic, commercial, and research use.
- **Data Attributions:**
  - [OurAirports](https://ourairports.com/data/) (Public Domain / CC0)
  - [OpenStreetMap](https://www.openstreetmap.org/) (ODbL)
  - [Wikidata](https://www.wikidata.org/) (CC0)
- **EPSG Authority:** Reprojected using `EPSG:7755` (India National Coordinate System - Metric) for precise spatial distance computations.
