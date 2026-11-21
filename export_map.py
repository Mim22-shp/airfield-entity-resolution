"""
Export Resolved Airfield Points to CSV
Airfield Entity Resolution Project Plan

Exports flattened source record mappings with master entity IDs,
coordinates, metadata, and conflict status for QGIS and Streamlit visualization.
"""

from config import DB_URL
import os
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine(DB_URL)

def run_export_map_csv():
    print("=" * 60)
    print("STAGE 7: Exporting Clustered Points to CSV for Mapping")
    print("=" * 60)

    query = """
    SELECT 
        r.entity_id AS master_uuid,
        r.cluster_size,
        r.is_singleton,
        r.has_conflict,
        r.conflict_types,
        a.source_table,
        a.source_id,
        a.raw_name,
        a.clean_name,
        a.icao_code,
        a.iata_code,
        a.mapped_type,
        a.latitude,
        a.longitude
    FROM resolved_entities r
    JOIN normalized_airfields a ON r.source_id = a.source_id
    ORDER BY r.cluster_size DESC, r.entity_id;
    """

    df_export = pd.read_sql(query, engine)
    output_path = os.path.join(os.path.dirname(__file__), "resolved_airfields_map.csv")
    df_export.to_csv(output_path, index=False)

    print(f"Success! Exported {len(df_export)} clustered source points to '{output_path}'.")
    return output_path

if __name__ == '__main__':
    run_export_map_csv()
