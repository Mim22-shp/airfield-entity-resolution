"""
Export Resolved Airfields to GeoJSON
Airfield Entity Resolution Project Plan

Exports resolved master entities from PostGIS to GeoJSON for GIS tools (QGIS, Mapbox, Leaflet).
Includes canonical metadata, cluster size, merged sources, and conflict flags.
"""

from config import DB_URL
import os
import geopandas as gpd
from sqlalchemy import create_engine

engine = create_engine(DB_URL)

def run_export_geojson():
    print("=" * 60)
    print("STAGE 6: Exporting Resolved Entities to GeoJSON")
    print("=" * 60)

    export_sql = """
    SELECT 
        entity_id,
        primary_name,
        canonical_icao,
        canonical_iata,
        primary_type AS category,
        record_count AS records_merged,
        sources_merged,
        max_spread_m,
        has_conflict,
        conflict_types,
        conflict_summary,
        geometry
    FROM entity_summary;
    """

    print("Querying entity_summary from PostGIS...")
    gdf = gpd.read_postgis(export_sql, engine, geom_col='geometry')

    output_path = os.path.join(os.path.dirname(__file__), "resolved_airfields.geojson")
    gdf.to_file(output_path, driver="GeoJSON")

    print(f"Success! Exported {len(gdf)} resolved airfields to '{output_path}'.")
    return output_path

if __name__ == '__main__':
    run_export_geojson()
