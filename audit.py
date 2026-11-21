"""
Audit Trail & Operational Scrutiny: why_linked(entity_id)
Airfield Entity Resolution Project Plan

Implements:
1. SQL Function why_linked(target_id TEXT):
   Returns full feature evidence, weights, ruleset version, and reasoning
   for all pairwise links in the resolved entity.
2. SQL Function why_linked_summary(target_id TEXT):
   Produces a formatted operational audit report string.
3. Python CLI runner for ad-hoc inspection and validation.
"""

from config import DB_URL
import os
import sys
import pandas as pd
from sqlalchemy import create_engine, text

engine = create_engine(DB_URL)

SQL_INSTALL_AUDIT_FUNCTIONS = """
-- 1. Tabular Audit Function: why_linked
CREATE OR REPLACE FUNCTION why_linked(target_id TEXT)
RETURNS TABLE (
    entity_id TEXT,
    id_a TEXT,
    name_a TEXT,
    type_a TEXT,
    icao_a TEXT,
    id_b TEXT,
    name_b TEXT,
    type_b TEXT,
    icao_b TEXT,
    distance_m DOUBLE PRECISION,
    dist_score DOUBLE PRECISION,
    name_sim_score DOUBLE PRECISION,
    code_match_score DOUBLE PRECISION,
    type_compat_score DOUBLE PRECISION,
    weight_name DOUBLE PRECISION,
    weight_dist DOUBLE PRECISION,
    weight_code DOUBLE PRECISION,
    weight_type DOUBLE PRECISION,
    final_confidence DOUBLE PRECISION,
    band TEXT,
    ruleset_version TEXT,
    reason_narrative TEXT,
    decision_timestamp TIMESTAMP WITHOUT TIME ZONE
) AS $$
DECLARE
    resolved_uuid TEXT;
BEGIN
    -- Allow query by either entity_id (UUID) or source_id
    SELECT re.entity_id INTO resolved_uuid
    FROM resolved_entities re
    WHERE re.entity_id = target_id OR re.source_id = target_id
    LIMIT 1;

    IF resolved_uuid IS NULL THEN
        resolved_uuid := target_id;
    END IF;

    RETURN QUERY
    SELECT 
        resolved_uuid AS entity_id,
        me.id_a,
        me.name_a,
        me.type_a,
        me.icao_a,
        me.id_b,
        me.name_b,
        me.type_b,
        me.icao_b,
        me.distance_m,
        me.dist_score,
        me.name_sim_score,
        me.code_match_score,
        me.type_compat_score,
        me.weight_name,
        me.weight_dist,
        me.weight_code,
        me.weight_type,
        me.final_confidence,
        me.band,
        me.ruleset_version,
        me.reason_narrative,
        me.decision_timestamp
    FROM match_evidence me
    JOIN resolved_entities re_a ON me.id_a = re_a.source_id
    JOIN resolved_entities re_b ON me.id_b = re_b.source_id
    WHERE re_a.entity_id = resolved_uuid 
      AND re_b.entity_id = resolved_uuid
      AND me.band = 'auto-merge'
    ORDER BY me.final_confidence DESC;
END;
$$ LANGUAGE plpgsql;

-- 2. Formatted Human-Readable Operational Audit Report: why_linked_summary
CREATE OR REPLACE FUNCTION why_linked_summary(target_id TEXT)
RETURNS TEXT AS $$
DECLARE
    resolved_uuid TEXT;
    entity_rec RECORD;
    pair_rec RECORD;
    report TEXT := '';
    link_idx INT := 1;
BEGIN
    SELECT re.entity_id INTO resolved_uuid
    FROM resolved_entities re
    WHERE re.entity_id = target_id OR re.source_id = target_id
    LIMIT 1;

    IF resolved_uuid IS NULL THEN
        RETURN 'Error: Entity or source ID not found: ' || target_id;
    END IF;

    SELECT * INTO entity_rec 
    FROM entity_summary 
    WHERE entity_summary.entity_id = resolved_uuid;

    report := report || E'================================================================================\n';
    report := report || E'AIRFIELD ENTITY RESOLUTION AUDIT REPORT\n';
    report := report || E'================================================================================\n';
    report := report || 'Entity ID        : ' || resolved_uuid || E'\n';
    report := report || 'Canonical Name   : ' || COALESCE(entity_rec.primary_name, 'N/A') || E'\n';
    report := report || 'ICAO / IATA      : ' || COALESCE(entity_rec.canonical_icao, 'None') || ' / ' || COALESCE(entity_rec.canonical_iata, 'None') || E'\n';
    report := report || 'Mapped Type      : ' || COALESCE(entity_rec.primary_type, 'N/A') || E'\n';
    report := report || 'Records Merged   : ' || COALESCE(entity_rec.record_count::text, '1') || ' (' || COALESCE(entity_rec.sources_merged, 'N/A') || E')\n';
    report := report || 'Coordinates      : (' || ROUND(entity_rec.centroid_lat::numeric, 5) || ', ' || ROUND(entity_rec.centroid_lon::numeric, 5) || E')\n';
    report := report || 'Spatial Spread   : ' || ROUND(COALESCE(entity_rec.max_spread_m, 0)::numeric, 1) || E' meters\n';
    report := report || 'Conflict Status  : ' || CASE WHEN entity_rec.has_conflict THEN 'FLAGGED CONFLICT -> ' || entity_rec.conflict_summary ELSE 'CLEAN MERGE (No Conflicts)' END || E'\n';
    report := report || E'--------------------------------------------------------------------------------\n';
    report := report || E'DECISION EVIDENCE TRAIL (Ruleset Version ' || COALESCE(entity_rec.conflict_types, 'v1.0') || E'):\n';

    FOR pair_rec IN SELECT * FROM why_linked(resolved_uuid) LOOP
        report := report || E'\n[Link ' || link_idx || E'] ' || pair_rec.id_a || ' <---> ' || pair_rec.id_b || E'\n';
        report := report || '  - Names         : "' || pair_rec.name_a || '" vs "' || pair_rec.name_b || E'"\n';
        report := report || '  - Name Sim      : ' || ROUND(pair_rec.name_sim_score::numeric, 3) || ' (weight: ' || pair_rec.weight_name || E')\n';
        report := report || '  - Distance      : ' || ROUND(pair_rec.distance_m::numeric, 1) || ' m (Score: ' || ROUND(pair_rec.dist_score::numeric, 3) || ', weight: ' || pair_rec.weight_dist || E')\n';
        report := report || '  - Code Match    : ' || ROUND(pair_rec.code_match_score::numeric, 2) || ' (weight: ' || pair_rec.weight_code || E')\n';
        report := report || '  - Type Compat   : ' || ROUND(pair_rec.type_compat_score::numeric, 2) || ' (' || pair_rec.type_a || ' vs ' || pair_rec.type_b || ', weight: ' || pair_rec.weight_type || E')\n';
        report := report || '  - Combined Conf : ' || ROUND(pair_rec.final_confidence::numeric, 3) || ' [Decision: ' || UPPER(pair_rec.band) || E']\n';
        report := report || '  - Stored Reason : ' || pair_rec.reason_narrative || E'\n';
        report := report || '  - Timestamp     : ' || pair_rec.decision_timestamp::text || E'\n';
        link_idx := link_idx + 1;
    END LOOP;

    IF link_idx = 1 THEN
        report := report || E'  (Singleton record - no pairwise merge links)\n';
    END IF;

    report := report || E'================================================================================\n';
    RETURN report;
END;
$$ LANGUAGE plpgsql;
"""

def install_audit_functions():
    print("Installing PostgreSQL audit functions 'why_linked' and 'why_linked_summary'...")
    with engine.begin() as conn:
        conn.execute(text(SQL_INSTALL_AUDIT_FUNCTIONS))
    print("Success: Audit functions installed into PostGIS database.")


def audit_entity(target_id):
    """Executes why_linked for a given entity or source ID and prints the report."""
    with engine.connect() as conn:
        report = conn.execute(
            text("SELECT why_linked_summary(:id);"), 
            {"id": target_id}
        ).scalar()
        print(report)


def run_sample_audits():
    install_audit_functions()

    print("\n" + "=" * 60)
    print("AUDIT DEMONSTRATION: Operational Scrutiny on Sample Entities")
    print("=" * 60)

    # 1. Clean multi-record merge
    query_clean = """
    SELECT entity_id, primary_name, record_count, sources_merged
    FROM entity_summary
    WHERE record_count >= 2 AND NOT has_conflict
    ORDER BY record_count DESC
    LIMIT 1;
    """
    df_clean = pd.read_sql(query_clean, engine)

    if not df_clean.empty:
        clean_id = df_clean.iloc[0]['entity_id']
        print(f"\n[DEMO 1] Auditing Clean Multi-Source Merge Entity:")
        audit_entity(clean_id)

    # 2. Flagged conflict entity (if any)
    query_conflict = """
    SELECT entity_id, primary_name, record_count, conflict_types
    FROM entity_summary
    WHERE has_conflict
    LIMIT 1;
    """
    df_conflict = pd.read_sql(query_conflict, engine)

    if not df_conflict.empty:
        conf_id = df_conflict.iloc[0]['entity_id']
        print(f"\n[DEMO 2] Auditing Flagged Conflict Entity:")
        audit_entity(conf_id)
    else:
        print("\n[DEMO 2] No conflict entities detected under current guardrails.")

    # 3. Singleton entity
    query_single = """
    SELECT entity_id, primary_name
    FROM entity_summary
    WHERE record_count = 1
    LIMIT 1;
    """
    df_single = pd.read_sql(query_single, engine)
    if not df_single.empty:
        single_id = df_single.iloc[0]['entity_id']
        print(f"\n[DEMO 3] Auditing Singleton Airfield:")
        audit_entity(single_id)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        install_audit_functions()
        audit_entity(sys.argv[1])
    else:
        run_sample_audits()
