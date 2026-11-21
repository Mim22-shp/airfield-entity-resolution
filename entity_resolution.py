"""
Stage 5: Resolve and Graph with Conflict Detection
Airfield Entity Resolution Project Plan

Builds a NetworkX graph:
- Source records as nodes
- Auto-merge links as confidence-weighted edges
- Connected components as resolved master entities

Conflict Detection Engine:
1. Coordinate spread conflicts: merged points > 5 km apart
2. Code conflicts: multiple distinct ICAO/IATA codes inside a single entity
3. Multi-entity ambiguity conflicts: records having borderline cross-entity links
4. Type incompatibility: e.g. standalone helipads merged with major commercial airports

Outputs in PostGIS:
- resolved_entities: row per source record with master entity_id
- entity_summary: master airfield rollup with canonical metadata, centroids, and conflict flags
- resolution_conflicts: operational audit log of all flagged anomalies
- airfield_graph.html: interactive NetworkX visualization of merged clusters
"""

from config import DB_URL
import os
import uuid
import datetime
import math
import pandas as pd
import geopandas as gpd
from sqlalchemy.engine import create_engine
from sqlalchemy.sql import text
import networkx as nx
from pyvis.network import Network

engine = create_engine(DB_URL)

MAX_ALLOWED_SPREAD_M = 5000.0  # 5 km threshold


def haversine_distance_m(lat1, lon1, lat2, lon2):
    """Calculates great-circle distance in meters between two lat/lon points."""
    if any(pd.isna(v) for v in (lat1, lon1, lat2, lon2)):
        return 0.0
    r = 6371000.0  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def export_interactive_html(G, output_html="airfield_graph.html"):
    """
    Exports multi-record merged clusters from the NetworkX graph
    into an interactive browser visualization using PyVis.
    """
    print("\nGenerating interactive graph visualization...")
    net = Network(height="850px", width="100%", bgcolor="#1a1a1a", font_color="white", cdn_resources='in_line')

    # Filter out isolated singletons (focus on multi-record merges)
    connected_nodes = [node for node, deg in dict(G.degree()).items() if deg > 0]
    if not connected_nodes:
        print("No connected edges found to visualize.")
        return

    subG = G.subgraph(connected_nodes)

    # Distinct colors by source table
    source_colors = {
        'ourairports': '#4fc3f7',  # light blue
        'aai': '#81c784',          # soft green
        'mil': '#ffb74d'           # amber/orange
    }

    # Add nodes with rich metadata tooltips
    for node, data in subG.nodes(data=True):
        src_table = data.get('source_table', 'unknown')
        color = source_colors.get(src_table, '#ba68c8')
        raw_name = data.get('raw_name') or str(node)
        
        hover_info = (
            f"<b>Source ID:</b> {node}<br>"
            f"<b>Source Dataset:</b> {src_table}<br>"
            f"<b>Airfield Name:</b> {raw_name}<br>"
            f"<b>Mapped Type:</b> {data.get('mapped_type', 'N/A')}<br>"
            f"<b>ICAO:</b> {data.get('icao_code', 'N/A')}<br>"
            f"<b>IATA:</b> {data.get('iata_code', 'N/A')}<br>"
            f"<b>Coordinates:</b> ({data.get('latitude')}, {data.get('longitude')})"
        )
        
        display_label = f"{src_table}: {raw_name[:24]}"
        net.add_node(
            node,
            label=display_label,
            title=hover_info,
            color=color,
            size=22
        )

    # Add edges with match evidence tooltips
    for u, v, data in subG.edges(data=True):
        conf = data.get('weight', 1.0)
        dist = data.get('distance_m', 0.0)
        reason = data.get('reason', 'Auto-merged link')

        edge_info = (
            f"<b>Pair:</b> {u} &harr; {v}<br>"
            f"<b>Match Confidence:</b> {conf:.2f}<br>"
            f"<b>Distance:</b> {dist:.1f} m<br>"
            f"<b>Evidence:</b> {reason}"
        )
        net.add_edge(
            u, v,
            title=edge_info,
            value=max(1, int(conf * 5)),
            color="#888888"
        )

    # Enable physics for smooth layout and interactive dragging
    net.toggle_physics(True)
    
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_html)
    html_content = net.generate_html()
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Interactive graph saved to: {output_path}")
    print(f" -> Merged nodes visualized: {len(connected_nodes)}")
    print(f" -> Merge edges visualized: {subG.number_of_edges()}")


def run_resolution():
    print("=" * 60)
    print("STAGE 5: Graph Resolution & Operational Conflict Detection")
    print("=" * 60)

    # 1. Fetch all normalized records
    print("Fetching normalized airfield nodes...")
    nodes_query = """
    SELECT 
        source_id, source_table, raw_name, clean_name,
        icao_code, iata_code, mapped_type,
        latitude, longitude
    FROM normalized_airfields;
    """
    df_nodes = pd.read_sql(nodes_query, engine)
    nodes_dict = df_nodes.set_index('source_id').to_dict(orient='index')
    print(f"Loaded {len(df_nodes)} distinct source nodes.")

    # 2. Fetch confident auto-merge edges
    print("Fetching auto-merge edges from match_evidence...")
    edges_query = """
    SELECT 
        id_a, id_b, distance_m, final_confidence, reason_narrative
    FROM match_evidence
    WHERE band = 'auto-merge';
    """
    df_edges = pd.read_sql(edges_query, engine)
    print(f"Loaded {len(df_edges)} auto-merge edges.")

    # 3. Build NetworkX Graph
    G = nx.Graph()
    for src_id, data in nodes_dict.items():
        G.add_node(src_id, **data)

    for _, row in df_edges.iterrows():
        G.add_edge(
            row['id_a'], 
            row['id_b'], 
            weight=row['final_confidence'],
            distance_m=row['distance_m'],
            reason=row['reason_narrative']
        )

    # 4. Extract Connected Components
    clusters = list(nx.connected_components(G))
    print(f"Extracted {len(clusters)} connected components (entities).")

    # 4b. Generate Interactive HTML Graph
    export_interactive_html(G, output_html="airfield_graph.html")

    # 5. Fetch borderline human-review pairs to detect cross-entity link ambiguities
    review_query = """
    SELECT id_a, id_b, final_confidence
    FROM match_evidence
    WHERE band = 'human-review' AND final_confidence >= 0.55;
    """
    df_review = pd.read_sql(review_query, engine)

    # Map source_id -> entity_id
    src_to_entity = {}
    cluster_entities = []
    now = datetime.datetime.now()

    for cluster in clusters:
        # Generate stable UUID derived from sorted source IDs
        sorted_members = sorted(list(cluster))
        entity_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, "-".join(sorted_members)))
        for member in sorted_members:
            src_to_entity[member] = entity_uuid
        cluster_entities.append((entity_uuid, sorted_members))

    # Pre-build lookup of cross-entity borderline edges for ambiguity detection
    borderline_cross_links = {}
    for _, rev in df_review.iterrows():
        ent_a = src_to_entity.get(rev['id_a'])
        ent_b = src_to_entity.get(rev['id_b'])
        if ent_a and ent_b and ent_a != ent_b:
            borderline_cross_links.setdefault(ent_a, []).append((rev['id_a'], rev['id_b'], ent_b, rev['final_confidence']))
            borderline_cross_links.setdefault(ent_b, []).append((rev['id_b'], rev['id_a'], ent_a, rev['final_confidence']))

    # 6. Process Entities & Conflict Detection
    resolved_rows = []
    summary_rows = []
    conflict_rows = []

    for entity_uuid, members in cluster_entities:
        cluster_size = len(members)
        is_singleton = (cluster_size == 1)

        # Collect member attributes
        member_records = [nodes_dict[m] for m in members]
        lats = [r['latitude'] for r in member_records if pd.notna(r['latitude'])]
        lons = [r['longitude'] for r in member_records if pd.notna(r['longitude'])]
        icaos = list({r['icao_code'] for r in member_records if r['icao_code']})
        iatas = list({r['iata_code'] for r in member_records if r['iata_code']})
        types = list({r['mapped_type'] for r in member_records if r['mapped_type']})
        sources = list({r['source_table'] for r in member_records if r['source_table']})

        # Canonical attributes
        # Prefer OurAirports name or longest name
        def name_priority(r):
            prio = 2 if r['source_table'] == 'ourairports' else 1
            return (prio, len(r['raw_name'] or ''))

        best_record = max(member_records, key=name_priority)
        primary_name = best_record['raw_name']
        primary_type = best_record['mapped_type']
        canonical_icao = icaos[0] if icaos else None
        canonical_iata = iatas[0] if iatas else None

        centroid_lat = sum(lats) / len(lats) if lats else None
        centroid_lon = sum(lons) / len(lons) if lons else None

        # Conflict Evaluation
        conflicts = []

        # Check A: Max coordinate distance across merged records
        max_dist_m = 0.0
        if cluster_size > 1 and len(lats) > 1:
            for i in range(len(lats)):
                for j in range(i + 1, len(lats)):
                    d = haversine_distance_m(lats[i], lons[i], lats[j], lons[j])
                    if d > max_dist_m:
                        max_dist_m = d

            if max_dist_m > MAX_ALLOWED_SPREAD_M:
                conf_desc = f"Merged records span {max_dist_m:.0f}m apart (exceeds {MAX_ALLOWED_SPREAD_M:.0f}m threshold)"
                conflicts.append(('COORDINATE_CONFLICT', 'HIGH', conf_desc))

        # Check B: Conflicting verified codes
        if len(icaos) > 1:
            conf_desc = f"Entity contains conflicting ICAO codes: {icaos}"
            conflicts.append(('CODE_CONFLICT', 'HIGH', conf_desc))
        if len(iatas) > 1:
            conf_desc = f"Entity contains conflicting IATA codes: {iatas}"
            conflicts.append(('CODE_CONFLICT', 'MEDIUM', conf_desc))

        # Check C: Type Incompatibility (helipad vs commercial airport)
        if 'helipad' in types and 'commercial' in types:
            conf_desc = f"Entity merges disparate types: {types}"
            conflicts.append(('TYPE_CONFLICT', 'MEDIUM', conf_desc))

        # Check D: Ambiguous cross-entity link (merged cluster has candidate links to other entities)
        if not is_singleton and entity_uuid in borderline_cross_links:
            cross_links = borderline_cross_links[entity_uuid]
            for src_this, src_other, other_ent, c_score in cross_links[:2]:
                conf_desc = f"Record {src_this} has candidate review link to {src_other} in entity {other_ent[:8]}... (confidence: {c_score:.2f})"
                conflicts.append(('AMBIGUOUS_LINK_CONFLICT', 'MEDIUM', conf_desc))

        has_conflict = len(conflicts) > 0
        conflict_types_str = "; ".join(c[0] for c in conflicts) if has_conflict else None
        conflict_details_str = "; ".join(c[2] for c in conflicts) if has_conflict else None

        # Record conflicts in operational table
        for c_type, c_sev, c_desc in conflicts:
            conflict_rows.append({
                'entity_id': entity_uuid,
                'conflict_type': c_type,
                'severity': c_sev,
                'description': c_desc,
                'involved_sources': ",".join(members),
                'detected_at': now
            })

        # Resolved entities rows (one per source record)
        for member in members:
            resolved_rows.append({
                'source_id': member,
                'entity_id': entity_uuid,
                'cluster_size': cluster_size,
                'is_singleton': is_singleton,
                'has_conflict': has_conflict,
                'conflict_types': conflict_types_str,
                'conflict_details': conflict_details_str,
                'resolved_at': now
            })

        # Summary row
        summary_rows.append({
            'entity_id': entity_uuid,
            'primary_name': primary_name,
            'canonical_icao': canonical_icao,
            'canonical_iata': canonical_iata,
            'primary_type': primary_type,
            'record_count': cluster_size,
            'sources_merged': ",".join(sorted(sources)),
            'centroid_lat': centroid_lat,
            'centroid_lon': centroid_lon,
            'max_spread_m': round(max_dist_m, 2),
            'has_conflict': has_conflict,
            'conflict_types': conflict_types_str,
            'conflict_summary': conflict_details_str,
            'resolved_at': now
        })

    df_resolved = pd.DataFrame(resolved_rows)
    df_summary = pd.DataFrame(summary_rows)
    df_conflicts = pd.DataFrame(conflict_rows)

    print(f"\nResolution Results:")
    print(f" - Total Source Records Mapped: {len(df_resolved)}")
    print(f" - Unique Resolved Entities    : {len(df_summary)}")
    multi_records = df_summary[df_summary['record_count'] > 1]
    print(f" - Multi-Record Merged Entities: {len(multi_records)}")
    print(f" - Flagged Conflict Entities   : {len(df_summary[df_summary['has_conflict']])}")
    print(f" - Total Conflicts Logged      : {len(df_conflicts)}")

    # 7. Write to PostGIS
    print("\nPersisting tables to PostGIS...")
    df_resolved.to_sql('resolved_entities', engine, if_exists='replace', index=False)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE resolved_entities ADD PRIMARY KEY (source_id);"))
        conn.execute(text("CREATE INDEX idx_re_entity_id ON resolved_entities(entity_id);"))
        conn.execute(text("CREATE INDEX idx_re_conflict ON resolved_entities(has_conflict);"))

    # Entity summary as GeoDataFrame
    valid_summary = df_summary[df_summary['centroid_lat'].notna() & df_summary['centroid_lon'].notna()].copy()
    gdf_summary = gpd.GeoDataFrame(
        valid_summary,
        geometry=gpd.points_from_xy(valid_summary.centroid_lon, valid_summary.centroid_lat),
        crs="EPSG:4326"
    )
    gdf_summary.to_postgis('entity_summary', engine, if_exists='replace', index=False)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE entity_summary ADD PRIMARY KEY (entity_id);"))
        conn.execute(text("CREATE INDEX idx_es_geom ON entity_summary USING GIST(geometry);"))
        conn.execute(text("CREATE INDEX idx_es_conflict ON entity_summary(has_conflict);"))

    if not df_conflicts.empty:
        df_conflicts.to_sql('resolution_conflicts', engine, if_exists='replace', index=False)
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX idx_rc_entity ON resolution_conflicts(entity_id);"))
            conn.execute(text("CREATE INDEX idx_rc_type ON resolution_conflicts(conflict_type);"))

    print("Stage 5 Complete: Graph components resolved and conflict guardrails established.")

if __name__ == '__main__':
    run_resolution()
