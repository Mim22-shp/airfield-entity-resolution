"""
FastAPI Service: Airfield Entity Resolution
Exposes REST endpoints for querying resolved entities and operational explainability:
- GET /health               : Service health & database connectivity
- GET /entities             : Paginated list and search across resolved master airfields
- GET /entity/{id}          : Canonical details for a specific entity or source ID
- GET /entity/{id}/why      : Detailed audit trail & explainability evidence for why records were merged
"""

import os
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("AIRFIELDS_DB_URL")


# ---------------------------------------------------------------------------
# Database Management & Dependency Injection
# ---------------------------------------------------------------------------
_engine: Optional[Engine] = None

def get_engine() -> Optional[Engine]:
    """Returns the global SQLAlchemy engine, initializing if DB_URL is set."""
    global _engine
    if _engine is None and DB_URL:
        try:
            _engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)
        except Exception:
            _engine = None
    return _engine


def get_db():
    """Dependency that yields a database connection. Can be overridden in tests."""
    engine = get_engine()
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is not configured or unavailable."
        )
    with engine.connect() as conn:
        yield conn


# ---------------------------------------------------------------------------
# Pydantic Response Schemas
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str
    version: str = "1.0.0"
    database_connected: bool
    db_message: str


class Centroid(BaseModel):
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class EntitySummary(BaseModel):
    entity_id: str
    primary_name: Optional[str] = None
    canonical_icao: Optional[str] = None
    canonical_iata: Optional[str] = None
    primary_type: Optional[str] = None
    record_count: int
    sources_merged: Optional[str] = None
    centroid: Centroid
    spatial_spread_m: Optional[float] = None
    has_conflict: bool
    conflict_types: Optional[str] = None
    conflict_summary: Optional[str] = None


class PairwiseMatchEvidence(BaseModel):
    id_a: str
    name_a: Optional[str] = None
    type_a: Optional[str] = None
    icao_a: Optional[str] = None
    id_b: str
    name_b: Optional[str] = None
    type_b: Optional[str] = None
    icao_b: Optional[str] = None
    distance_m: Optional[float] = None
    dist_score: Optional[float] = None
    name_sim_score: Optional[float] = None
    code_match_score: Optional[float] = None
    type_compat_score: Optional[float] = None
    weights: Dict[str, float]
    final_confidence: float
    band: str
    ruleset_version: Optional[str] = None
    reason_narrative: Optional[str] = None
    decision_timestamp: Optional[str] = None


class EntityWhyResponse(BaseModel):
    target_id: str
    resolved_entity_id: str
    entity: EntitySummary
    is_singleton: bool
    records_merged: List[str]
    pairwise_links_count: int
    pairwise_links: List[PairwiseMatchEvidence]
    explanation_narrative: str


# ---------------------------------------------------------------------------
# FastAPI Application Setup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup validation
    eng = get_engine()
    if eng:
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1;"))
        except Exception:
            pass
    yield


app = FastAPI(
    title="Airfield Entity Resolution API",
    description="Operational explainability and query API for resolved geospatial airfield records.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/", tags=["General"])
def root():
    """Welcome and quick documentation link."""
    return {
        "title": "Airfield Entity Resolution API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_url": "/health",
        "sample_why_url": "/entity/{id}/why"
    }


@app.get("/health", response_model=HealthResponse, tags=["General"])
def health():
    """Returns the service health status and verifies live database connectivity."""
    engine = get_engine()
    if engine is None:
        return HealthResponse(
            status="degraded",
            database_connected=False,
            db_message="AIRFIELDS_DB_URL is not set or engine initialization failed."
        )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1;"))
        return HealthResponse(
            status="healthy",
            database_connected=True,
            db_message="Connected to PostGIS database."
        )
    except Exception as exc:
        return HealthResponse(
            status="degraded",
            database_connected=False,
            db_message=f"Database unreachable: {str(exc)}"
        )


@app.get("/entities", response_model=List[EntitySummary], tags=["Entities"])
def list_entities(
    limit: int = Query(20, ge=1, le=100, description="Max entities to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    search: Optional[str] = Query(None, description="Filter by name or code substring"),
    has_conflict: Optional[bool] = Query(None, description="Filter by conflict status"),
    conn=Depends(get_db)
):
    """Lists resolved master entities with optional search and conflict filtering."""
    query = """
        SELECT 
            entity_id, primary_name, canonical_icao, canonical_iata,
            primary_type, record_count, sources_merged, centroid_lat, centroid_lon,
            max_spread_m, has_conflict, conflict_types, conflict_summary
        FROM entity_summary
        WHERE 1=1
    """
    params = {"limit": limit, "offset": offset}

    if search:
        query += " AND (primary_name ILIKE :search OR canonical_icao ILIKE :search OR canonical_iata ILIKE :search)"
        params["search"] = f"%{search}%"

    if has_conflict is not None:
        query += " AND has_conflict = :has_conflict"
        params["has_conflict"] = has_conflict

    query += " ORDER BY record_count DESC, primary_name ASC LIMIT :limit OFFSET :offset;"

    rows = conn.execute(text(query), params).mappings().fetchall()
    results = []
    for r in rows:
        results.append(
            EntitySummary(
                entity_id=r["entity_id"],
                primary_name=r["primary_name"],
                canonical_icao=r["canonical_icao"],
                canonical_iata=r["canonical_iata"],
                primary_type=r["primary_type"],
                record_count=int(r["record_count"] or 1),
                sources_merged=r["sources_merged"],
                centroid=Centroid(
                    latitude=r["centroid_lat"],
                    longitude=r["centroid_lon"]
                ),
                spatial_spread_m=r["max_spread_m"],
                has_conflict=bool(r["has_conflict"]),
                conflict_types=r["conflict_types"],
                conflict_summary=r["conflict_summary"],
            )
        )
    return results


@app.get("/entity/{id}", response_model=EntitySummary, tags=["Entities"])
def get_entity(id: str, conn=Depends(get_db)):
    """Fetches canonical entity summary for a given master entity_id (UUID) or source_id."""
    # Resolve target_id to master entity_id
    res_id_row = conn.execute(
        text("SELECT entity_id FROM resolved_entities WHERE entity_id = :id OR source_id = :id LIMIT 1;"),
        {"id": id}
    ).fetchone()

    resolved_id = res_id_row[0] if res_id_row else id

    row = conn.execute(
        text("""
            SELECT 
                entity_id, primary_name, canonical_icao, canonical_iata,
                primary_type, record_count, sources_merged, centroid_lat, centroid_lon,
                max_spread_m, has_conflict, conflict_types, conflict_summary
            FROM entity_summary
            WHERE entity_id = :resolved_id
            LIMIT 1;
        """),
        {"resolved_id": resolved_id}
    ).mappings().fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity or source '{id}' not found in resolved entities."
        )

    return EntitySummary(
        entity_id=row["entity_id"],
        primary_name=row["primary_name"],
        canonical_icao=row["canonical_icao"],
        canonical_iata=row["canonical_iata"],
        primary_type=row["primary_type"],
        record_count=int(row["record_count"] or 1),
        sources_merged=row["sources_merged"],
        centroid=Centroid(
            latitude=row["centroid_lat"],
            longitude=row["centroid_lon"]
        ),
        spatial_spread_m=row["max_spread_m"],
        has_conflict=bool(row["has_conflict"]),
        conflict_types=row["conflict_types"],
        conflict_summary=row["conflict_summary"],
    )


@app.get(
    "/entity/{id}/why",
    response_model=EntityWhyResponse,
    responses={
        200: {
            "description": "Evidence and mathematical breakdown for why records were merged into this entity.",
            "content": {
                "application/json": {},
                "text/plain": {"schema": {"type": "string"}}
            }
        },
        404: {"description": "Entity or source ID not found."}
    },
    tags=["Explainability & Audit"]
)
def get_entity_why(
    id: str,
    format: str = Query("json", pattern="^(json|text)$", description="Response format: 'json' (default) or 'text' for formatted ASCII audit report"),
    conn=Depends(get_db)
):
    """
    Explainability Endpoint: /entity/{id}/why
    
    Provides the exact mathematical evidence, component weights, pairwise match scores,
    and narrative justifications behind why records were merged into this entity.
    
    Accepts either a master entity_id (UUID) or any raw source record ID (e.g. 'osm_747078123', 'ourairports_42716').
    Supports '?format=text' for human-readable audit summaries or default JSON.
    """
    # 1. Resolve target ID to master entity_id
    res_id_row = conn.execute(
        text("SELECT entity_id FROM resolved_entities WHERE entity_id = :id OR source_id = :id LIMIT 1;"),
        {"id": id}
    ).fetchone()

    resolved_id = res_id_row[0] if res_id_row else id

    # 2. Query entity summary
    summary_row = conn.execute(
        text("""
            SELECT 
                entity_id, primary_name, canonical_icao, canonical_iata,
                primary_type, record_count, sources_merged, centroid_lat, centroid_lon,
                max_spread_m, has_conflict, conflict_types, conflict_summary
            FROM entity_summary
            WHERE entity_id = :resolved_id
            LIMIT 1;
        """),
        {"resolved_id": resolved_id}
    ).mappings().fetchone()

    if not summary_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entity or source '{id}' not found."
        )

    # 3. If plain text report is requested, call why_linked_summary directly
    if format == "text":
        report_text = conn.execute(
            text("SELECT why_linked_summary(:target_id);"),
            {"target_id": resolved_id}
        ).scalar()
        return PlainTextResponse(content=report_text or "No report generated.", media_type="text/plain")

    # 4. Fetch constituent source records
    source_records = conn.execute(
        text("SELECT source_id FROM resolved_entities WHERE entity_id = :resolved_id ORDER BY source_id;"),
        {"resolved_id": resolved_id}
    ).scalars().all()
    if not source_records:
        source_records = [resolved_id]

    # 5. Fetch pairwise linkage evidence from why_linked stored function
    pairwise_rows = conn.execute(
        text("SELECT * FROM why_linked(:resolved_id);"),
        {"resolved_id": resolved_id}
    ).mappings().fetchall()

    pairwise_links: List[PairwiseMatchEvidence] = []
    for r in pairwise_rows:
        pairwise_links.append(
            PairwiseMatchEvidence(
                id_a=r["id_a"],
                name_a=r["name_a"],
                type_a=r["type_a"],
                icao_a=r["icao_a"],
                id_b=r["id_b"],
                name_b=r["name_b"],
                type_b=r["type_b"],
                icao_b=r["icao_b"],
                distance_m=r["distance_m"],
                dist_score=r["dist_score"],
                name_sim_score=r["name_sim_score"],
                code_match_score=r["code_match_score"],
                type_compat_score=r["type_compat_score"],
                weights={
                    "name": r["weight_name"],
                    "dist": r["weight_dist"],
                    "code": r["weight_code"],
                    "type": r["weight_type"],
                },
                final_confidence=r["final_confidence"],
                band=r["band"],
                ruleset_version=r["ruleset_version"],
                reason_narrative=r["reason_narrative"],
                decision_timestamp=str(r["decision_timestamp"]) if r["decision_timestamp"] else None,
            )
        )

    is_singleton = len(source_records) <= 1 or len(pairwise_links) == 0

    if is_singleton:
        narrative = (
            f"Entity '{summary_row['primary_name']}' is a singleton airfield containing 1 source record "
            f"({summary_row['sources_merged'] or 'unknown'}). No cross-source pairwise merges exceeded the 0.80 auto-merge threshold."
        )
    else:
        narrative = (
            f"Entity '{summary_row['primary_name']}' resolved from {summary_row['record_count']} source records "
            f"({summary_row['sources_merged']}) via {len(pairwise_links)} auto-merge graph link(s). "
            f"Maximum spatial spread: {round(summary_row['max_spread_m'] or 0, 1)}m. "
            f"Conflict status: {'FLAGGED CONFLICT (' + (summary_row['conflict_summary'] or '') + ')' if summary_row['has_conflict'] else 'CLEAN MERGE (No Conflicts)'}."
        )

    entity_summary_obj = EntitySummary(
        entity_id=summary_row["entity_id"],
        primary_name=summary_row["primary_name"],
        canonical_icao=summary_row["canonical_icao"],
        canonical_iata=summary_row["canonical_iata"],
        primary_type=summary_row["primary_type"],
        record_count=int(summary_row["record_count"] or 1),
        sources_merged=summary_row["sources_merged"],
        centroid=Centroid(
            latitude=summary_row["centroid_lat"],
            longitude=summary_row["centroid_lon"]
        ),
        spatial_spread_m=summary_row["max_spread_m"],
        has_conflict=bool(summary_row["has_conflict"]),
        conflict_types=summary_row["conflict_types"],
        conflict_summary=summary_row["conflict_summary"],
    )

    return EntityWhyResponse(
        target_id=id,
        resolved_entity_id=resolved_id,
        entity=entity_summary_obj,
        is_singleton=is_singleton,
        records_merged=list(source_records),
        pairwise_links_count=len(pairwise_links),
        pairwise_links=pairwise_links,
        explanation_narrative=narrative,
    )
