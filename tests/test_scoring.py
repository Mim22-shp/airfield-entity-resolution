"""
Unit tests for core scoring, distance, and entity resolution logic.
Tests pure functions from scoring.py and entity_resolution.py.
"""

import pytest
import pandas as pd
from scoring import (
    compute_distance_score,
    compute_code_match,
    compute_type_compatibility,
    compute_name_similarity
)
from entity_resolution import haversine_distance_m


def test_distance_score_decay():
    """Validates metric distance linear decay: 0m -> 1.0, 5000m -> 0.5, >=10000m -> 0.0."""
    assert compute_distance_score(0) == 1.0
    assert compute_distance_score(5000) == 0.5
    assert compute_distance_score(10000) == 0.0
    assert compute_distance_score(15000) == 0.0
    assert compute_distance_score(None) == 0.0


def test_code_match_logic():
    """
    Validates ICAO / IATA code verification returns (score, status, detail):
    - (1.0, 'match', code) for matching code
    - (0.0, 'conflict', desc) for conflicting code
    - (0.5, 'neutral', 'none') for neutral / missing code
    """
    # 1. Matching ICAO
    row_match = pd.Series({'icao_a': 'VIDP', 'icao_b': 'VIDP', 'iata_a': 'DEL', 'iata_b': 'DEL'})
    score, status, detail = compute_code_match(row_match)
    assert score == 1.0
    assert status == "match"
    assert detail == "VIDP"

    # 2. Conflicting ICAO
    row_conflict = pd.Series({'icao_a': 'VIDP', 'icao_b': 'VABB', 'iata_a': None, 'iata_b': None})
    score, status, detail = compute_code_match(row_conflict)
    assert score == 0.0
    assert status == "conflict"
    assert "VIDP!=VABB" in detail

    # 3. Neutral (missing on one or both sides)
    row_neutral = pd.Series({'icao_a': 'VIDP', 'icao_b': None, 'iata_a': None, 'iata_b': None})
    score, status, detail = compute_code_match(row_neutral)
    assert score == 0.5
    assert status == "neutral"


def test_type_compatibility_matrix():
    """Validates facility type compatibility matrix."""
    assert compute_type_compatibility('commercial', 'commercial') == 1.0
    assert compute_type_compatibility('commercial', 'general_aviation') == 0.75
    assert compute_type_compatibility('military', 'commercial') == 0.60
    assert compute_type_compatibility('helipad', 'commercial') == 0.15


def test_name_similarity_fuzz():
    """Validates RapidFuzz name similarity handling exact matches, token order, and non-matches."""
    row_exact = pd.Series({'name_a': 'mumbai airport', 'name_b': 'mumbai airport', 'raw_name_a': 'mumbai airport', 'raw_name_b': 'mumbai airport'})
    assert compute_name_similarity(row_exact) == 1.0

    # Token sort ratio handles word re-ordering
    row_reorder = pd.Series({'name_a': 'delhi international airport', 'name_b': 'airport international delhi', 'raw_name_a': 'delhi international airport', 'raw_name_b': 'airport international delhi'})
    assert compute_name_similarity(row_reorder) == 1.0

    # Disparate names fall below non-match threshold (0.50)
    row_diff = pd.Series({'name_a': 'cochin naval base', 'name_b': 'amritsar international', 'raw_name_a': 'cochin naval base', 'raw_name_b': 'amritsar international'})
    assert compute_name_similarity(row_diff) < 0.50


def test_haversine_distance_m():
    """Validates spherical great-circle distance calculation."""
    # Distance from VIDP (Delhi: 28.5665, 77.1031) to VABB (Mumbai: 19.0896, 72.8656) is ~1148 km
    dist = haversine_distance_m(28.5665, 77.1031, 19.0896, 72.8656)
    assert 1100000 < dist < 1200000

    # Co-located points
    assert haversine_distance_m(28.5, 77.1, 28.5, 77.1) == 0.0
