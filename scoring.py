"""
Stage 4: Pairwise Scoring & Audit Evidence
Airfield Entity Resolution Project Plan

Computes multi-feature confidence scores for each candidate pair:
1. Name similarity (Rapidfuzz token_set_ratio & token_sort_ratio)
2. Spatial distance score (metric decay up to 10 km)
3. Exact code match (ICAO and IATA agreement, conflict, or neutrality)
4. Type compatibility (commercial, helipad, military civil-enclave, etc.)

Combines features using simple calibrated weights into a 0.0 - 1.0 confidence score
with three decision bands:
- 'auto-merge'    (confidence >= 0.80)
- 'human-review'  (0.50 <= confidence < 0.80)
- 'non-match'     (confidence < 0.50)

Records every feature value, weight, ruleset version, and narrative reason to 'match_evidence'.
"""

from config import DB_URL
import os
import datetime
import pandas as pd
from sqlalchemy import create_engine, text
from rapidfuzz import fuzz

engine = create_engine(DB_URL)

RULESET_VERSION = "v1.0"
W_NAME = 0.35
W_DIST = 0.30
W_CODE = 0.20
W_TYPE = 0.15


def compute_name_similarity(row):
    """Calculates name similarity between 0.0 and 1.0 using RapidFuzz."""
    name_a = str(row['name_a'] or row['raw_name_a'] or '').strip().lower()
    name_b = str(row['name_b'] or row['raw_name_b'] or '').strip().lower()

    if not name_a or not name_b:
        return 0.0
    if name_a == name_b:
        return 1.0

    ratio_set = fuzz.token_set_ratio(name_a, name_b)
    ratio_sort = fuzz.token_sort_ratio(name_a, name_b)
    best_ratio = max(ratio_set, ratio_sort) / 100.0
    return round(best_ratio, 4)


def compute_distance_score(dist_m):
    """Converts metric distance into 0.0 - 1.0 score (0m = 1.0, 10,000m = 0.0)."""
    if pd.isna(dist_m) or dist_m is None:
        return 0.0
    score = max(0.0, 1.0 - (float(dist_m) / 10000.0))
    return round(score, 4)


def compute_code_match(row):
    """
    Evaluates ICAO and IATA code alignment:
    - 1.0: Exact ICAO or IATA match
    - 0.0: Conflicting verified codes
    - 0.5: Neutral (one or both records lack code)
    """
    icao_a = (str(row['icao_a']).strip().upper()) if pd.notna(row['icao_a']) and row['icao_a'] else None
    icao_b = (str(row['icao_b']).strip().upper()) if pd.notna(row['icao_b']) and row['icao_b'] else None
    iata_a = (str(row['iata_a']).strip().upper()) if pd.notna(row['iata_a']) and row['iata_a'] else None
    iata_b = (str(row['iata_b']).strip().upper()) if pd.notna(row['iata_b']) and row['iata_b'] else None

    # Check for direct matches
    icao_matches = (icao_a is not None and icao_b is not None and icao_a == icao_b)
    iata_matches = (iata_a is not None and iata_b is not None and iata_a == iata_b)

    if icao_matches or iata_matches:
        return 1.0, "match", (icao_a if icao_matches else iata_a)

    # Check for conflicts
    icao_conflicts = (icao_a is not None and icao_b is not None and len(icao_a) == 4 and len(icao_b) == 4 and icao_a != icao_b)
    iata_conflicts = (iata_a is not None and iata_b is not None and len(iata_a) == 3 and len(iata_b) == 3 and iata_a != iata_b)

    if icao_conflicts or iata_conflicts:
        conflict_desc = f"{icao_a}!={icao_b}" if icao_conflicts else f"{iata_a}!={iata_b}"
        return 0.0, "conflict", conflict_desc

    return 0.5, "neutral", "none"


def compute_type_compatibility(type_a, type_b):
    """Evaluates airfield classification compatibility."""
    t_a = str(type_a).lower().strip() if pd.notna(type_a) else 'other'
    t_b = str(type_b).lower().strip() if pd.notna(type_b) else 'other'

    if t_a == t_b:
        return 1.0
    # Commercial and General Aviation are highly compatible
    if {t_a, t_b} == {'commercial', 'general_aviation'}:
        return 0.75
    # Military air base & Commercial (frequent Indian joint civil enclaves e.g. Pune, Goa)
    if {t_a, t_b} == {'military', 'commercial'}:
        return 0.60
    # Other is neutral
    if 'other' in (t_a, t_b):
        return 0.50
    # Closed vs active
    if 'closed' in (t_a, t_b):
        return 0.20
    # Helipad vs Commercial Airport
    if {t_a, t_b} == {'helipad', 'commercial'}:
        return 0.15
    return 0.30


def score_pairs(df_pairs):
    print("Computing features and confidence scores...")
    now = datetime.datetime.now()

    scores = []
    for _, row in df_pairs.iterrows():
        dist_m = row['distance_m']
        name_sim = compute_name_similarity(row)
        dist_score = compute_distance_score(dist_m)
        code_score, code_status, code_detail = compute_code_match(row)
        type_score = compute_type_compatibility(row['type_a'], row['type_b'])

        # Base weighted confidence score (0.0 to 1.0)
        final_conf = (
            (W_NAME * name_sim) +
            (W_DIST * dist_score) +
            (W_CODE * code_score) +
            (W_TYPE * type_score)
        )

        # Domain Guardrails
        # 1. Exact verified code match + within 5km is overwhelming evidence
        if code_status == "match" and dist_m <= 5000:
            final_conf = max(final_conf, 0.92)

        # 2. Conflicting verified 4-letter ICAO codes: hard veto (different facilities)
        if code_status == "conflict":
            final_conf = min(final_conf, 0.25)

        # 3. No code match and distance > 10 km
        if dist_m > 10000 and code_status != "match":
            final_conf = min(final_conf, 0.20)

        final_conf = round(max(0.0, min(1.0, final_conf)), 4)

        # Assign Merge Band
        if final_conf >= 0.80:
            band = 'auto-merge'
        elif final_conf >= 0.50:
            band = 'human-review'
        else:
            band = 'non-match'

        # Build reason narrative for operational scrutiny
        narrative_parts = []
        if code_status == "match":
            narrative_parts.append(f"Exact code match ({code_detail})")
        elif code_status == "conflict":
            narrative_parts.append(f"Conflicting codes ({code_detail})")

        narrative_parts.append(f"dist: {dist_m:.0f}m (dist_score: {dist_score:.2f})")
        narrative_parts.append(f"name_sim: {name_sim:.2f}")
        narrative_parts.append(f"types: {row['type_a']} vs {row['type_b']} (compat: {type_score:.2f})")
        narrative_parts.append(f"band: {band}")
        reason_narrative = "; ".join(narrative_parts)

        scores.append({
            'pair_id': row['pair_id'],
            'id_a': row['id_a'],
            'name_a': row['name_a'],
            'raw_name_a': row['raw_name_a'],
            'type_a': row['type_a'],
            'icao_a': row['icao_a'],
            'iata_a': row['iata_a'],
            'id_b': row['id_b'],
            'name_b': row['name_b'],
            'raw_name_b': row['raw_name_b'],
            'type_b': row['type_b'],
            'icao_b': row['icao_b'],
            'iata_b': row['iata_b'],
            'distance_m': dist_m,
            'dist_score': dist_score,
            'name_sim_score': name_sim,
            'code_match_score': code_score,
            'type_compat_score': type_score,
            'weight_name': W_NAME,
            'weight_dist': W_DIST,
            'weight_code': W_CODE,
            'weight_type': W_TYPE,
            'final_confidence': final_conf,
            'band': band,
            'ruleset_version': RULESET_VERSION,
            'reason_narrative': reason_narrative,
            'decision_timestamp': now
        })

    return pd.DataFrame(scores)


def run_scoring():
    print("=" * 60)
    print("STAGE 4: Multi-Feature Scoring & Audit Trail Generation")
    print("=" * 60)

    query = """
    SELECT 
        pair_id,
        id_a, name_a, raw_name_a, type_a, icao_a, iata_a,
        id_b, name_b, raw_name_b, type_b, icao_b, iata_b,
        distance_m
    FROM candidate_pairs;
    """
    df_pairs = pd.read_sql(query, engine)
    print(f"Loaded {len(df_pairs)} candidate pairs from PostGIS.")

    if df_pairs.empty:
        print("Warning: No candidate pairs found to score.")
        return

    df_evidence = score_pairs(df_pairs)

    print("\nBand Distribution:")
    band_counts = df_evidence['band'].value_counts()
    for b_name, count in band_counts.items():
        print(f" - {b_name}: {count} pairs ({count / len(df_evidence) * 100:.1f}%)")

    # Save to PostGIS match_evidence table
    print("\nSaving match evidence with full decision features to 'match_evidence'...")
    df_evidence.to_sql('match_evidence', engine, if_exists='replace', index=False)

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE match_evidence ADD PRIMARY KEY (pair_id);"))
        conn.execute(text("CREATE INDEX idx_me_id_a ON match_evidence(id_a);"))
        conn.execute(text("CREATE INDEX idx_me_id_b ON match_evidence(id_b);"))
        conn.execute(text("CREATE INDEX idx_me_band ON match_evidence(band);"))
        conn.execute(text("CREATE INDEX idx_me_conf ON match_evidence(final_confidence);"))

    print("Success! match_evidence table populated with audit trail.")

    print("\n--- SAMPLE AUTO-MERGE DECISIONS ---")
    auto_sample = df_evidence[df_evidence['band'] == 'auto-merge'][
        ['name_a', 'name_b', 'distance_m', 'name_sim_score', 'final_confidence', 'reason_narrative']
    ].head(3)
    print(auto_sample.to_string(index=False))

    print("\n--- SAMPLE HUMAN-REVIEW DECISIONS ---")
    rev_sample = df_evidence[df_evidence['band'] == 'human-review'][
        ['name_a', 'name_b', 'distance_m', 'name_sim_score', 'final_confidence', 'reason_narrative']
    ].head(3)
    print(rev_sample.to_string(index=False))


if __name__ == '__main__':
    run_scoring()
