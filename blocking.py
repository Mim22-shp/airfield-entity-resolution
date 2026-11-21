"""
Stage 3: Candidate Generation (Blocking) in PostGIS
Airfield Entity Resolution Project Plan

Pairs only records within ~10 km (ST_DWithin) OR sharing an ICAO/IATA code,
preventing Cartesian N^2 comparisons.

Key features:
- Pairs distinct records with a.source_id < b.source_id (avoids self/duplicate pairs)
- Distance in meters calculated via metric CRS (EPSG:7755)
- Records exact blocking rule ('spatial_10km', 'icao_match', 'iata_match', 'spatial_and_code')
- Generates integer primary key 'pair_id'
- Indexes generated table for fast scoring queries
"""

from config import DB_URL
import os
from sqlalchemy import create_engine, text

engine = create_engine(DB_URL)

def run_blocking():
    print("=" * 60)
    print("STAGE 3: Candidate Generation (Blocking via PostGIS)")
    print("=" * 60)

    blocking_sql = """
    DROP TABLE IF EXISTS candidate_pairs CASCADE;

    CREATE TABLE candidate_pairs AS
    SELECT 
        ROW_NUMBER() OVER (ORDER BY a.source_id, b.source_id) AS pair_id,
        
        -- Source A attributes
        a.source_table AS source_table_a,
        a.source_id AS id_a,
        a.raw_name AS raw_name_a,
        a.clean_name AS name_a,
        a.mapped_type AS type_a,
        a.icao_code AS icao_a,
        a.iata_code AS iata_a,
        a.latitude AS lat_a,
        a.longitude AS lon_a,
        
        -- Source B attributes
        b.source_table AS source_table_b,
        b.source_id AS id_b,
        b.raw_name AS raw_name_b,
        b.clean_name AS name_b,
        b.mapped_type AS type_b,
        b.icao_code AS icao_b,
        b.iata_code AS iata_b,
        b.latitude AS lat_b,
        b.longitude AS lon_b,
        
        -- Distance in meters (EPSG:7755)
        ROUND(ST_Distance(a.geom_metric, b.geom_metric)::numeric, 2) AS distance_m,
        
        -- Recorded blocking reason
        CASE 
            WHEN ST_DWithin(a.geom_metric, b.geom_metric, 10000) 
                 AND ((a.icao_code IS NOT NULL AND a.icao_code = b.icao_code) OR (a.iata_code IS NOT NULL AND a.iata_code = b.iata_code))
                THEN 'spatial_and_code'
            WHEN ST_DWithin(a.geom_metric, b.geom_metric, 10000) 
                THEN 'spatial_10km'
            WHEN a.icao_code IS NOT NULL AND a.icao_code = b.icao_code 
                THEN 'icao_match'
            WHEN a.iata_code IS NOT NULL AND a.iata_code = b.iata_code 
                THEN 'iata_match'
            ELSE 'other'
        END AS block_rule

    FROM normalized_airfields a
    JOIN normalized_airfields b 
      ON a.source_id < b.source_id
    WHERE 
      -- Blocking Rule 1: Within 10 km
      ST_DWithin(a.geom_metric, b.geom_metric, 10000)
      OR 
      -- Blocking Rule 2: Exact ICAO match (non-null/non-empty)
      (a.icao_code IS NOT NULL AND a.icao_code != '' AND a.icao_code = b.icao_code)
      OR 
      -- Blocking Rule 3: Exact IATA match (non-null/non-empty)
      (a.iata_code IS NOT NULL AND a.iata_code != '' AND a.iata_code = b.iata_code);

    -- Primary key & indices for high-performance downstream scoring
    ALTER TABLE candidate_pairs ADD PRIMARY KEY (pair_id);
    CREATE INDEX idx_cp_id_a ON candidate_pairs(id_a);
    CREATE INDEX idx_cp_id_b ON candidate_pairs(id_b);
    CREATE INDEX idx_cp_dist ON candidate_pairs(distance_m);
    """

    print("Executing candidate blocking query...")
    with engine.begin() as conn:
        conn.execute(text(blocking_sql))
        count = conn.execute(text("SELECT COUNT(*) FROM candidate_pairs;")).scalar()
        rule_breakdown = conn.execute(text("""
            SELECT block_rule, COUNT(*) 
            FROM candidate_pairs 
            GROUP BY block_rule 
            ORDER BY COUNT(*) DESC;
        """)).fetchall()

    print(f"\nSuccess! Generated {count} candidate pairs for scoring.")
    print("\nCandidate Blocking Breakdown:")
    for rule, cnt in rule_breakdown:
        print(f" - {rule}: {cnt} pairs")

if __name__ == '__main__':
    run_blocking()
