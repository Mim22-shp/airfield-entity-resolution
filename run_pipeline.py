"""
Master End-to-End Orchestrator: Airfield Entity Resolution
Airfield Entity Resolution Project Plan

Runs all 5 build stages + audit + export in sequence:
1. Ingest      -> PostGIS raw tables (OurAirports, OSM, Wikidata)
2. Normalize   -> PostGIS normalized_airfields view
3. Blocking    -> PostGIS candidate_pairs table (spatial 10km + ICAO/IATA)
4. Scoring     -> PostGIS match_evidence table (rapidfuzz, dist, code, type)
5. Resolution  -> PostGIS resolved_entities, entity_summary, resolution_conflicts
6. Audit       -> PostGIS stored functions why_linked & why_linked_summary
7. Export      -> GeoJSON and CSV files for QGIS and Streamlit
"""

import time
import sys
import ingest
import normalize
import blocking
import scoring
import entity_resolution
import audit
import export_data
import export_map

def main():
    skip_fetch = '--skip-fetch' in sys.argv or '--skip-existing' in sys.argv
    start_total = time.time()
    print("=" * 70)
    print("🚀 STARTING AIRFIELD ENTITY RESOLUTION PIPELINE")
    print(f"Mode: {'Fast re-run (using existing PostGIS raw tables)' if skip_fetch else 'Full run (with raw data fetch)'}")
    print("=" * 70)

    # Stage 1: Ingestion
    t0 = time.time()
    print("\n>>> STAGE 1: RAW INGESTION")
    ingest.main(skip_if_exists=skip_fetch)
    print(f"Stage 1 completed in {time.time() - t0:.2f}s")

    # Stage 2: Normalization
    t0 = time.time()
    print("\n>>> STAGE 2: NORMALIZATION VIEW")
    normalize.run_normalization()
    print(f"Stage 2 completed in {time.time() - t0:.2f}s")

    # Stage 3: Blocking
    t0 = time.time()
    print("\n>>> STAGE 3: CANDIDATE GENERATION (BLOCKING)")
    blocking.run_blocking()
    print(f"Stage 3 completed in {time.time() - t0:.2f}s")

    # Stage 4: Scoring
    t0 = time.time()
    print("\n>>> STAGE 4: MULTI-FEATURE SCORING & AUDIT EVIDENCE")
    scoring.run_scoring()
    print(f"Stage 4 completed in {time.time() - t0:.2f}s")

    # Stage 5: Resolution & Conflict Detection
    t0 = time.time()
    print("\n>>> STAGE 5: GRAPH RESOLUTION & CONFLICT DETECTION")
    entity_resolution.run_resolution()
    print(f"Stage 5 completed in {time.time() - t0:.2f}s")

    # Stage 6: Audit Functions
    t0 = time.time()
    print("\n>>> STAGE 6: AUDIT TRAIL INSTALLATION & VALIDATION")
    audit.run_sample_audits()
    print(f"Stage 6 completed in {time.time() - t0:.2f}s")

    # Stage 7: Exports
    t0 = time.time()
    print("\n>>> STAGE 7: EXPORTS (GEOJSON & CSV)")
    export_data.run_export_geojson()
    export_map.run_export_map_csv()
    print(f"Stage 7 completed in {time.time() - t0:.2f}s")

    print("\n" + "=" * 70)
    print(f"✅ PIPELINE SUCCESSFULLY COMPLETED IN {time.time() - start_total:.2f}s")
    print("=" * 70)

if __name__ == '__main__':
    main()
