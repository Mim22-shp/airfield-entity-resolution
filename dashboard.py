"""
Interactive Streamlit Dashboard: Airfield Entity Resolution
Visualizes deduplication metrics, spatial distributions, flagged conflicts,
NetworkX graph clusters, and an operational 'Why Linked?' audit explorer.
"""

import os
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from sqlalchemy.engine import create_engine
from sqlalchemy.sql import text
import networkx as nx
from pyvis.network import Network

# Database Engine
def _get_db_url():
    url = os.getenv("AIRFIELDS_DB_URL")
    if url:
        return url
    try:
        return st.secrets["AIRFIELDS_DB_URL"]
    except Exception:
        return None

DB_URL = _get_db_url()

st.set_page_config(
    page_title="Airfield Entity Resolution",
    page_icon="✈️",
    layout="wide"
)

st.title("🛩️ Airfield Entity Resolution Dashboard")
st.caption("PostGIS & NetworkX Entity Resolution with Multi-Feature Scoring, Interactive Graph Visualization, and Operational Audit Trails")


@st.cache_resource
def get_db_engine():
    if not DB_URL:
        return None
    try:
        return create_engine(DB_URL)
    except Exception as e:
        st.error(f"Failed to connect to database: {e}")
        return None


engine = get_db_engine()


# Load summary and points
@st.cache_data(ttl=60)
def load_data():
    map_csv_path = os.path.join(os.path.dirname(__file__), "resolved_airfields_map.csv")
    if not os.path.exists(map_csv_path):
        return None, None
    df_points = pd.read_csv(map_csv_path)

    if engine:
        try:
            df_summary = pd.read_sql("""
                SELECT 
                    entity_id, primary_name, canonical_icao, canonical_iata,
                    primary_type, record_count, sources_merged,
                    centroid_lat, centroid_lon, max_spread_m,
                    has_conflict, conflict_types, conflict_summary
                FROM entity_summary;
            """, engine)
        except Exception:
            df_summary = None
    else:
        df_summary = None

    return df_points, df_summary


df_points, df_summary = load_data()

if df_points is None:
    st.warning("⚠️ No resolved data found ('resolved_airfields_map.csv' missing). Please run the resolution pipeline first.")
    st.stop()


def render_entity_graph(entity_uuid, df_points, engine, height="500px"):
    """
    Renders an interactive PyVis NetworkX graph for a single resolved entity.
    """
    sub_df = df_points[df_points['master_uuid'] == entity_uuid]
    if sub_df.empty:
        st.info("No records found for this entity.")
        return

    source_ids = list(sub_df['source_id'].dropna().unique())
    G = nx.Graph()

    for _, row in sub_df.iterrows():
        G.add_node(
            row['source_id'],
            raw_name=row['raw_name'],
            source_table=row['source_table'],
            icao_code=row.get('icao_code'),
            iata_code=row.get('iata_code'),
            mapped_type=row.get('mapped_type'),
            latitude=row.get('latitude'),
            longitude=row.get('longitude')
        )

    # Fetch edges from database if connected
    if engine and len(source_ids) > 1:
        try:
            with engine.connect() as conn:
                query = text("""
                    SELECT id_a, id_b, distance_m, final_confidence, reason_narrative
                    FROM match_evidence
                    WHERE id_a = ANY(:ids) AND id_b = ANY(:ids) AND band = 'auto-merge';
                """)
                edges_df = pd.read_sql(query, conn, params={"ids": source_ids})
                for _, erow in edges_df.iterrows():
                    G.add_edge(
                        erow['id_a'],
                        erow['id_b'],
                        weight=float(erow['final_confidence']),
                        distance_m=float(erow['distance_m']),
                        reason=erow['reason_narrative']
                    )
        except Exception as e:
            st.warning(f"Could not load edge evidence: {e}")

    # Build PyVis Network
    net = Network(height=height, width="100%", bgcolor="#1a1a1a", font_color="white", cdn_resources='in_line')
    source_colors = {
        'ourairports': '#4fc3f7',
        'aai': '#81c784',
        'mil': '#ffb74d'
    }

    for node, data in G.nodes(data=True):
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
        net.add_node(
            node,
            label=f"{src_table}: {raw_name[:24]}",
            title=hover_info,
            color=color,
            size=24
        )

    for u, v, data in G.edges(data=True):
        conf = data.get('weight', 1.0)
        dist = data.get('distance_m', 0.0)
        reason = data.get('reason', 'Auto-merged')
        edge_info = (
            f"<b>Pair:</b> {u} &harr; {v}<br>"
            f"<b>Confidence:</b> {conf:.2f}<br>"
            f"<b>Distance:</b> {dist:.1f} m<br>"
            f"<b>Reason:</b> {reason}"
        )
        net.add_edge(
            u, v,
            title=edge_info,
            value=max(1, int(conf * 5)),
            color="#00adb5"
        )

    net.toggle_physics(True)
    html_content = net.generate_html()
    components.html(html_content, height=int(height.replace("px", "")) + 20)


# Key Pipeline Metrics
total_raw = len(df_points)
total_entities = df_points['master_uuid'].nunique()
merged_entities = len(df_points[df_points['cluster_size'] > 1]['master_uuid'].unique())
duplicates_merged = total_raw - total_entities
conflicts_count = int(df_points[df_points['has_conflict'] == True]['master_uuid'].nunique())

st.subheader("📊 Resolution Pipeline Performance")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Raw Records", f"{total_raw:,}")
col2.metric("Master Entities", f"{total_entities:,}")
col3.metric("Multi-Source Merges", f"{merged_entities:,}")
col4.metric("Deduplicated Count", f"{duplicates_merged:,}")
col5.metric("Flagged Conflicts", f"{conflicts_count:,}", delta_color="inverse")

tabs = st.tabs([
    "🗺️ Spatial Distribution & Filter",
    "🕸️ NetworkX Graph Visualizer",
    "⚠️ Conflict Inspection",
    "🔍 'Why Linked?' Audit Explorer",
    "📋 Raw Mappings"
])

# Tab 1: Map
with tabs[0]:
    st.subheader("Spatial Distribution of Indian Airfields")
    c1, c2, c3 = st.columns(3)

    types_list = ['All'] + sorted(list(df_points['mapped_type'].dropna().unique()))
    selected_type = c1.selectbox("Filter by Mapped Type", types_list)

    source_list = ['All'] + sorted(list(df_points['source_table'].dropna().unique()))
    selected_source = c2.selectbox("Filter by Source", source_list)

    filter_mode = c3.selectbox("Cluster Status", ["All Records", "Merged Entities Only (>1)", "Singletons Only", "Flagged Conflicts Only"])

    filtered_df = df_points.copy()
    if selected_type != 'All':
        filtered_df = filtered_df[filtered_df['mapped_type'] == selected_type]
    if selected_source != 'All':
        filtered_df = filtered_df[filtered_df['source_table'] == selected_source]
    if filter_mode == "Merged Entities Only (>1)":
        filtered_df = filtered_df[filtered_df['cluster_size'] > 1]
    elif filter_mode == "Singletons Only":
        filtered_df = filtered_df[filtered_df['cluster_size'] == 1]
    elif filter_mode == "Flagged Conflicts Only":
        filtered_df = filtered_df[filtered_df['has_conflict'] == True]

    st.write(f"Showing **{len(filtered_df)}** airfield points matching criteria:")

    map_df = filtered_df[['latitude', 'longitude']].dropna()
    if not map_df.empty:
        st.map(map_df)
    else:
        st.info("No airfield records match current filters.")

# Tab 2: NetworkX Graph Visualizer
with tabs[1]:
    st.subheader("🕸️ NetworkX Entity Resolution Graph Visualizer")
    st.markdown("Explore resolved source nodes, confidence-weighted merge links, and cluster connectivity interactively.")

    graph_view_mode = st.radio(
        "Select Graph Exploration Mode:",
        ["🎯 Single Entity Subgraph", "🌐 Global Merged Network"],
        horizontal=True
    )

    if graph_view_mode == "🎯 Single Entity Subgraph":
        merged_candidates = df_points[df_points['cluster_size'] > 1].copy()
        if not merged_candidates.empty:
            summary_grouped = merged_candidates.groupby('master_uuid').agg({
                'raw_name': 'first',
                'source_table': lambda s: ", ".join(sorted(set(s))),
                'cluster_size': 'first'
            }).reset_index()

            ent_options = {
                f"{row['raw_name']} ({row['cluster_size']} records | Sources: {row['source_table']} | UUID: {row['master_uuid'][:8]}...)": row['master_uuid']
                for _, row in summary_grouped.head(200).iterrows()
            }

            sel_entity_label = st.selectbox("Choose a Merged Airfield Entity to Inspect:", list(ent_options.keys()))
            chosen_uuid = ent_options[sel_entity_label]

            # Entity Overview Cards
            entity_records = df_points[df_points['master_uuid'] == chosen_uuid]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Merged Records", len(entity_records))
            m2.metric("Distinct Sources", entity_records['source_table'].nunique())
            m3.metric("Mapped Type", str(entity_records['mapped_type'].dropna().iloc[0]) if not entity_records['mapped_type'].dropna().empty else "N/A")
            has_conf = bool(entity_records['has_conflict'].iloc[0])
            m4.metric("Conflict Status", "⚠️ Flagged" if has_conf else "✅ Clean")

            st.caption("💡 **Tip:** Nodes and links are interactive: drag nodes to rearrange, scroll to zoom, hover for full attribute cards.")
            render_entity_graph(chosen_uuid, df_points, engine, height="550px")
        else:
            st.info("No multi-record merged entities found to display.")

    else:
        st.markdown("Interactive PyVis visualization of all auto-merged airfield clusters across India.")
        graph_html_path = os.path.join(os.path.dirname(__file__), "airfield_graph.html")

        if os.path.exists(graph_html_path):
            with open(graph_html_path, "r", encoding="utf-8") as f:
                full_graph_html = f.read()
            st.caption("Rendering interactive global graph (drag nodes to reposition, scroll to zoom in/out):")
            components.html(full_graph_html, height=850, scrolling=True)
        else:
            st.warning("⚠️ 'airfield_graph.html' not found. Run Stage 5 (`entity_resolution.py`) to generate the full graph file.")

# Tab 3: Conflict Inspection
with tabs[2]:
    st.subheader("Operational Scrutiny: Flagged Conflicts")
    st.markdown("Airfields flagged by automated guardrails (e.g. spatial spread > 5km, conflicting ICAO codes, or multi-entity borderline links).")

    if df_summary is not None:
        conflict_df = df_summary[df_summary['has_conflict'] == True]
        if not conflict_df.empty:
            st.dataframe(
                conflict_df[[
                    'entity_id', 'primary_name', 'canonical_icao', 'record_count', 
                    'sources_merged', 'max_spread_m', 'conflict_types', 'conflict_summary'
                ]],
                use_container_width=True
            )
        else:
            st.success("🎉 No entities flagged with conflicts! All merges comply with operational guardrails.")
    else:
        st.info("Connect to PostgreSQL to view comprehensive conflict details.")

# Tab 4: Why Linked? Audit Explorer
with tabs[3]:
    st.subheader("🔍 Operational Audit Trail: 'why_linked(entity_id)'")
    st.markdown("Answers the critical question: **'Why did you merge these records?'** with full feature weights, graph connectivity, and decision evidence.")

    if engine and df_summary is not None:
        merged_candidates = df_summary[df_summary['record_count'] > 1].copy()

        options = {
            f"{row['primary_name']} (UUID: {row['entity_id'][:8]}... | {row['sources_merged']})": row['entity_id']
            for _, row in merged_candidates.head(100).iterrows()
        }

        selected_label = st.selectbox("Select an Airfield Entity to Audit:", list(options.keys()))
        target_entity_uuid = options[selected_label]

        custom_id = st.text_input("Or enter any specific Entity ID or Source ID:")
        if custom_id.strip():
            target_entity_uuid = custom_id.strip()

        try:
            with engine.connect() as conn:
                audit_text = conn.execute(
                    text("SELECT why_linked_summary(:id);"), 
                    {"id": target_entity_uuid}
                ).scalar()

                pairs_df = pd.read_sql(
                    text("SELECT * FROM why_linked(:id);"), 
                    conn, 
                    params={"id": target_entity_uuid}
                )

            st.text_area("Full Operational Audit Report:", audit_text, height=280)

            if not pairs_df.empty:
                st.write("#### Pairwise Decision Feature Breakdown")
                st.dataframe(
                    pairs_df[[
                        'id_a', 'name_a', 'id_b', 'name_b', 
                        'distance_m', 'name_sim_score', 'code_match_score', 
                        'type_compat_score', 'final_confidence', 'band', 'reason_narrative'
                    ]],
                    use_container_width=True
                )

            # Also show the interactive mini-graph for the audited entity right here
            st.write("#### Entity Subgraph Connectivity")
            render_entity_graph(target_entity_uuid, df_points, engine, height="450px")

        except Exception as e:
            st.error(f"Error fetching audit data: {e}")
    else:
        st.warning("Database connection is required for dynamic SQL why_linked queries.")

# Tab 5: Raw Mappings
with tabs[4]:
    st.subheader("Resolved Entity Mappings Table")
    st.dataframe(df_points.head(200), use_container_width=True)
