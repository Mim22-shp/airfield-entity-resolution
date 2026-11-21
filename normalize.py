"""
Stage 2: Normalization View in PostGIS
Airfield Entity Resolution Project Plan

Normalizes raw airfield records across all sources (OurAirports, OSM, Wikidata):
- Lowercase names and strip noisy facility words ("airport", "air force station", "aerodrome", etc.)
- Map source-specific type labels into a single unified taxonomy
- Reproject geometries to a common metric CRS (EPSG:7755) and preserve EPSG:4326 lat/lon
- Clean and standardize ICAO / IATA codes
"""

from config import DB_URL
import os
from sqlalchemy import create_engine, text

engine = create_engine(DB_URL)

def run_normalization():
    print("=" * 60)
    print("STAGE 2: Normalizing Airfield Records & Creating PostGIS View")
    print("=" * 60)

    # Check which raw tables exist in PostGIS
    with engine.connect() as conn:
        tables = conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
              AND table_name IN ('raw_ourairports', 'raw_osm', 'raw_wikidata');
        """)).scalars().all()

    print(f"Detected raw tables: {tables}")
    has_oa = 'raw_ourairports' in tables
    has_osm = 'raw_osm' in tables
    has_wd = 'raw_wikidata' in tables

    if not has_oa and not has_osm:
        raise RuntimeError("Neither raw_ourairports nor raw_osm found in database. Run ingest.py first.")

    select_queries = []

    # 1. OurAirports Query
    if has_oa:
        select_queries.append("""
        SELECT 
            'ourairports' AS source_table,
            source_id,
            LOWER(TRIM(name)) AS raw_name,
            NULLIF(TRIM(REGEXP_REPLACE(
                REGEXP_REPLACE(
                    LOWER(name),
                    '\\[duplicate\\]|\\(.*?\\)|[^a-z0-9\\s]', 
                    ' ', 
                    'g'
                ),
                '\\b(airport|aerodrome|air force station|afs|air force base|airbase|heliport|helipad|airstrip|strip|international|domestic|civil enclave|civil aerodrome|enclave|flying club)\\b',
                ' ',
                'g'
            )), '') AS clean_name,
            CASE WHEN UPPER(TRIM(COALESCE(icao_code, ident))) ~ '^[A-Z]{4}$' THEN UPPER(TRIM(COALESCE(icao_code, ident))) ELSE NULL END AS icao_code,
            NULLIF(TRIM(UPPER(iata_code)), '') AS iata_code,
            CASE 
                WHEN type LIKE '%heliport%' OR type LIKE '%helipad%' THEN 'helipad'
                WHEN type IN ('large_airport', 'medium_airport') THEN 'commercial'
                WHEN type = 'small_airport' THEN 'general_aviation'
                WHEN type = 'closed' THEN 'closed'
                WHEN LOWER(name) LIKE '%air force%' OR LOWER(name) LIKE '%afs%' THEN 'military'
                ELSE 'other'
            END AS mapped_type,
            latitude_deg AS latitude,
            longitude_deg AS longitude,
            geometry AS geom_4326,
            ST_Transform(geometry, 7755) AS geom_metric
        FROM raw_ourairports
        WHERE geometry IS NOT NULL
        """)

    # 2. OSM Query
    if has_osm:
        select_queries.append("""
        SELECT 
            'osm' AS source_table,
            source_id,
            LOWER(TRIM(name)) AS raw_name,
            NULLIF(TRIM(REGEXP_REPLACE(
                REGEXP_REPLACE(
                    LOWER(name),
                    '\\[duplicate\\]|\\(.*?\\)|[^a-z0-9\\s]', 
                    ' ', 
                    'g'
                ),
                '\\b(airport|aerodrome|air force station|afs|air force base|airbase|heliport|helipad|airstrip|strip|international|domestic|civil enclave|civil aerodrome|enclave|flying club)\\b',
                ' ',
                'g'
            )), '') AS clean_name,
            CASE WHEN UPPER(TRIM(icao)) ~ '^[A-Z]{4}$' THEN UPPER(TRIM(icao)) ELSE NULL END AS icao_code,
            NULLIF(TRIM(UPPER(iata)), '') AS iata_code,
            CASE 
                WHEN type = 'helipad' THEN 'helipad'
                WHEN type = 'aerodrome' THEN 'commercial'
                WHEN LOWER(name) LIKE '%air force%' OR LOWER(name) LIKE '%afs%' THEN 'military'
                ELSE 'other'
            END AS mapped_type,
            lat AS latitude,
            lon AS longitude,
            geometry AS geom_4326,
            ST_Transform(geometry, 7755) AS geom_metric
        FROM raw_osm
        WHERE geometry IS NOT NULL
          AND name IS NOT NULL AND TRIM(name) != ''
        """)

    # 3. Wikidata Query (Three-Way Merge)
    if has_wd:
        select_queries.append("""
        SELECT 
            'wikidata' AS source_table,
            source_id,
            LOWER(TRIM(name)) AS raw_name,
            NULLIF(TRIM(REGEXP_REPLACE(
                REGEXP_REPLACE(
                    LOWER(name),
                    '\\[duplicate\\]|\\(.*?\\)|[^a-z0-9\\s]', 
                    ' ', 
                    'g'
                ),
                '\\b(airport|aerodrome|air force station|afs|air force base|airbase|heliport|helipad|airstrip|strip|international|domestic|civil enclave|civil aerodrome|enclave|flying club)\\b',
                ' ',
                'g'
            )), '') AS clean_name,
            CASE WHEN UPPER(TRIM(icao)) ~ '^[A-Z]{4}$' THEN UPPER(TRIM(icao)) ELSE NULL END AS icao_code,
            NULLIF(TRIM(UPPER(iata)), '') AS iata_code,
            CASE 
                WHEN LOWER(type) LIKE '%heliport%' OR LOWER(type) LIKE '%helipad%' THEN 'helipad'
                WHEN LOWER(type) LIKE '%military%' OR LOWER(type) LIKE '%air force%' OR LOWER(name) LIKE '%air force%' THEN 'military'
                WHEN LOWER(type) LIKE '%international%' OR LOWER(type) LIKE '%commercial%' OR LOWER(type) LIKE '%airport%' THEN 'commercial'
                WHEN LOWER(type) LIKE '%aerodrome%' THEN 'commercial'
                ELSE 'general_aviation'
            END AS mapped_type,
            lat AS latitude,
            lon AS longitude,
            geometry AS geom_4326,
            ST_Transform(geometry, 7755) AS geom_metric
        FROM raw_wikidata
        WHERE geometry IS NOT NULL
          AND name IS NOT NULL AND TRIM(name) != ''
        """)

    union_sql = "\nUNION ALL\n".join(select_queries)

    normalization_sql = f"""
    DROP VIEW IF EXISTS normalized_airfields CASCADE;

    CREATE VIEW normalized_airfields AS
    SELECT 
        source_table,
        source_id,
        raw_name,
        COALESCE(clean_name, raw_name) AS clean_name,
        icao_code,
        iata_code,
        mapped_type,
        latitude,
        longitude,
        geom_4326,
        geom_metric
    FROM (
        {union_sql}
    ) sub;
    """

    print("Executing normalization view definition in PostGIS...")
    with engine.begin() as conn:
        conn.execute(text(normalization_sql))
        count = conn.execute(text("SELECT COUNT(*) FROM normalized_airfields;")).scalar()
        breakdown = conn.execute(text("""
            SELECT source_table, mapped_type, COUNT(*) 
            FROM normalized_airfields 
            GROUP BY source_table, mapped_type 
            ORDER BY source_table, mapped_type;
        """)).fetchall()

    print(f"\nSuccess! View 'normalized_airfields' is ready with {count} total records.")
    print("\nSource & Type Distribution:")
    for row in breakdown:
        print(f" - [{row[0]}] {row[1]}: {row[2]}")

if __name__ == '__main__':
    run_normalization()
