"""
Stage 1: Raw Layer Ingestion in PostGIS
Airfield Entity Resolution Project

Builds the raw provenance foundation:
- One table per source, never edited in-place
- Each row tagged with unique source_id and load_timestamp
- Stores EPSG:4326 geometries with GIST spatial indices

Sources:
1. OurAirports CSV (airports in India) -> raw_ourairports
2. OpenStreetMap aeroway=aerodrome|helipad -> raw_osm
3. Wikidata Indian airports (SPARQL) -> raw_wikidata (Enables three-way merge)
"""

from config import DB_URL
import os
import sys
import datetime
import requests
import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine, text

engine = create_engine(DB_URL)


def prepare_db_for_ingest():
    """Drops dependent views before re-ingesting raw tables if needed."""
    with engine.begin() as conn:
        conn.execute(text("DROP VIEW IF EXISTS normalized_airfields CASCADE;"))


def ingest_ourairports(load_time):
    print("\n[1/3] Fetching OurAirports data...")
    oa_url = "https://davidmegginson.github.io/ourairports-data/airports.csv"
    try:
        df_oa = pd.read_csv(oa_url)
        df_oa_in = df_oa[df_oa['iso_country'] == 'IN'].copy()
        df_oa_in['source_id'] = 'ourairports_' + df_oa_in['id'].astype(str)
        df_oa_in['load_timestamp'] = load_time

        gdf_oa = gpd.GeoDataFrame(
            df_oa_in,
            geometry=gpd.points_from_xy(df_oa_in.longitude_deg, df_oa_in.latitude_deg),
            crs="EPSG:4326"
        )
        gdf_oa.to_postgis('raw_ourairports', engine, if_exists='replace', index=False)
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_oa_geom ON raw_ourairports USING GIST(geometry);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_oa_src_id ON raw_ourairports(source_id);"))
        print(f" -> Successfully loaded {len(gdf_oa)} OurAirports records to raw_ourairports.")
        return len(gdf_oa)
    except Exception as e:
        print(f" -> Error loading OurAirports: {e}. Retaining existing table if present.")
        try:
            with engine.connect() as conn:
                return conn.execute(text("SELECT COUNT(*) FROM raw_ourairports;")).scalar()
        except Exception:
            return 0


def ingest_osm(load_time):
    print("\n[2/3] Fetching OpenStreetMap aeroway data via Overpass API...")
    overpass_query = """
    [out:json][timeout:90];
    area["ISO3166-1"="IN"][admin_level=2]->.searchArea;
    (
      node["aeroway"~"aerodrome|helipad"](area.searchArea);
      way["aeroway"~"aerodrome|helipad"](area.searchArea);
    );
    out center;
    """
    custom_header = {'User-Agent': 'AirfieldEntityResolution_PortfolioProject/1.0 (contact@example.com)'}
    try:
        response = requests.get(
            "http://overpass-api.de/api/interpreter",
            params={'data': overpass_query},
            headers=custom_header,
            timeout=90
        )
        if response.status_code != 200:
            print(f" -> Overpass returned status code {response.status_code}, retaining existing raw_osm table.")
            with engine.connect() as conn:
                return conn.execute(text("SELECT COUNT(*) FROM raw_osm;")).scalar()

        osm_data = response.json()
        osm_records = []
        for element in osm_data.get('elements', []):
            lat = element.get('lat') or element.get('center', {}).get('lat')
            lon = element.get('lon') or element.get('center', {}).get('lon')
            tags = element.get('tags', {})

            if lat and lon:
                osm_records.append({
                    'osm_id': element['id'],
                    'type': tags.get('aeroway', ''),
                    'name': tags.get('name', ''),
                    'icao': tags.get('icao', '') or tags.get('ref', ''),
                    'iata': tags.get('iata', ''),
                    'lat': float(lat),
                    'lon': float(lon)
                })

        df_osm = pd.DataFrame(osm_records)
        df_osm['source_id'] = 'osm_' + df_osm['osm_id'].astype(str)
        df_osm['load_timestamp'] = load_time

        gdf_osm = gpd.GeoDataFrame(
            df_osm,
            geometry=gpd.points_from_xy(df_osm.lon, df_osm.lat),
            crs="EPSG:4326"
        )
        gdf_osm.to_postgis('raw_osm', engine, if_exists='replace', index=False)
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_osm_geom ON raw_osm USING GIST(geometry);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_osm_src_id ON raw_osm(source_id);"))
        print(f" -> Successfully loaded {len(gdf_osm)} OSM records to raw_osm.")
        return len(gdf_osm)
    except Exception as e:
        print(f" -> Note: Overpass request notice: {e}. Retaining existing raw_osm table.")
        try:
            with engine.connect() as conn:
                return conn.execute(text("SELECT COUNT(*) FROM raw_osm;")).scalar()
        except Exception:
            return 0


def ingest_wikidata(load_time):
    print("\n[3/3] Fetching Wikidata airports in India (three-way merge source)...")
    sparql_query = """
    SELECT ?item ?itemLabel ?icao ?iata ?coord WHERE {
      ?item wdt:P31/wdt:P279* wd:Q62447 ;
            wdt:P17 wd:Q668 ;
            wdt:P625 ?coord .
      OPTIONAL { ?item wdt:P239 ?icao . }
      OPTIONAL { ?item wdt:P238 ?iata . }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
    } LIMIT 600
    """
    wikidata_url = "https://query.wikidata.org/sparql"
    headers = {'User-Agent': 'AirfieldEntityResolution/1.0 (airfields-project@example.org)'}
    try:
        response = requests.get(
            wikidata_url,
            params={'query': sparql_query, 'format': 'json'},
            headers=headers,
            timeout=20
        )
        if response.status_code != 200:
            print(f" -> Wikidata returned status code {response.status_code}")
            return -1

        data = response.json()
        bindings = data.get('results', {}).get('bindings', [])

        records = []
        for b in bindings:
            qid = b['item']['value'].split('/')[-1]
            label = b.get('itemLabel', {}).get('value', '')
            icao = b.get('icao', {}).get('value', '')
            iata = b.get('iata', {}).get('value', '')
            coord_str = b.get('coord', {}).get('value', '')  # Point(lon lat)

            if coord_str.startswith('Point(') and coord_str.endswith(')'):
                coords = coord_str[6:-1].strip().split()
                if len(coords) == 2:
                    try:
                        lon = float(coords[0])
                        lat = float(coords[1])
                        records.append({
                            'wikidata_id': qid,
                            'name': label,
                            'icao': icao,
                            'iata': iata,
                            'type': 'airport',
                            'lat': lat,
                            'lon': lon
                        })
                    except ValueError:
                        continue

        if not records:
            print(" -> No Wikidata records parsed.")
            return -1

        df_wd = pd.DataFrame(records).drop_duplicates(subset=['wikidata_id'])
        df_wd['source_id'] = 'wikidata_' + df_wd['wikidata_id'].astype(str)
        df_wd['load_timestamp'] = load_time

        gdf_wd = gpd.GeoDataFrame(
            df_wd,
            geometry=gpd.points_from_xy(df_wd.lon, df_wd.lat),
            crs="EPSG:4326"
        )
        gdf_wd.to_postgis('raw_wikidata', engine, if_exists='replace', index=False)
        with engine.begin() as conn:
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_wd_geom ON raw_wikidata USING GIST(geometry);"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_raw_wd_src_id ON raw_wikidata(source_id);"))
        print(f" -> Successfully loaded {len(gdf_wd)} Wikidata records to raw_wikidata.")
        return len(gdf_wd)
    except Exception as e:
        print(f" -> Wikidata note: {e}. Proceeding with existing tables.")
        try:
            with engine.connect() as conn:
                return conn.execute(text("SELECT COUNT(*) FROM raw_wikidata;")).scalar()
        except Exception:
            return -1


def main(skip_if_exists=False):
    load_time = datetime.datetime.now()
    print("=" * 60)
    print(f"STAGE 1: Raw Layer Ingestion in PostGIS at {load_time}")
    print("=" * 60)

    # Check if tables already exist and skip_if_exists is set
    if skip_if_exists:
        with engine.connect() as conn:
            tables = conn.execute(text("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema='public' AND table_name IN ('raw_ourairports', 'raw_osm', 'raw_wikidata');
            """)).scalars().all()
            if 'raw_ourairports' in tables and 'raw_osm' in tables:
                print("Raw tables already exist in PostGIS. Skipping network download.")
                return

    prepare_db_for_ingest()

    oa_cnt = ingest_ourairports(load_time)
    osm_cnt = ingest_osm(load_time)
    wd_cnt = ingest_wikidata(load_time)

    print("\n--- Ingestion Summary ---")
    print(f"OurAirports : {oa_cnt} records")
    print(f"OSM         : {osm_cnt} records")
    print(f"Wikidata    : {wd_cnt} records")
    print("Stage 1 complete: Immutable raw provenance layer stored in PostGIS.")


if __name__ == '__main__':
    skip = '--skip-existing' in sys.argv
    main(skip_if_exists=skip)
