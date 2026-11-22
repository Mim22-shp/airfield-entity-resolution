import pytest
from fastapi.testclient import TestClient
from api import app, get_db

@pytest.fixture(scope="session")
def client():
    """Provides a TestClient for making HTTP requests against the FastAPI app."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_db_session():
    """
    Provides a mock database connection that simulates Postgres queries
    for testing the API in complete isolation from the database.
    """
    class MockMapping:
        def __init__(self, data):
            self._data = data

        def fetchone(self):
            return self._data[0] if self._data else None

        def fetchall(self):
            return self._data

    class MockScalars:
        def __init__(self, data):
            self._data = data

        def all(self):
            return self._data

        def first(self):
            return self._data[0] if self._data else None

    class MockResult:
        def __init__(self, data=None, scalar_val=None):
            self._data = data or []
            self._scalar_val = scalar_val

        def fetchone(self):
            return (self._data[0]["entity_id"],) if self._data else None

        def fetchall(self):
            return self._data

        def scalar(self):
            return self._scalar_val

        def mappings(self):
            return MockMapping(self._data)

        def scalars(self):
            return MockScalars([d.get("source_id", d.get("entity_id")) for d in self._data])

    class MockConnection:
        def execute(self, statement, parameters=None):
            sql = str(statement)
            params = parameters or {}
            target = params.get("id") or params.get("resolved_id") or params.get("target_id")

            # 1. Unknown ID -> empty
            if target == "non-existent-uuid-9999":
                return MockResult([])

            # 2. Resolved ID resolution
            if "SELECT entity_id FROM resolved_entities" in sql:
                if target in ["sample-multi-uuid", "source_osm_123", "source_oa_456"]:
                    return MockResult([{"entity_id": "sample-multi-uuid"}])
                if target == "sample-singleton-uuid":
                    return MockResult([{"entity_id": "sample-singleton-uuid"}])
                return MockResult([])

            # 3. Entity summary query
            if "FROM entity_summary" in sql:
                if target == "sample-multi-uuid":
                    return MockResult([{
                        "entity_id": "sample-multi-uuid",
                        "primary_name": "Sample International Airport",
                        "canonical_icao": "VIXX",
                        "canonical_iata": "SIA",
                        "primary_type": "commercial",
                        "record_count": 2,
                        "sources_merged": "osm,ourairports",
                        "centroid_lat": 28.567,
                        "centroid_lon": 77.123,
                        "max_spread_m": 120.5,
                        "has_conflict": False,
                        "conflict_types": None,
                        "conflict_summary": None,
                    }])
                elif target == "sample-singleton-uuid":
                    return MockResult([{
                        "entity_id": "sample-singleton-uuid",
                        "primary_name": "Isolated Remote Airstrip",
                        "canonical_icao": None,
                        "canonical_iata": None,
                        "primary_type": "general_aviation",
                        "record_count": 1,
                        "sources_merged": "ourairports",
                        "centroid_lat": 15.123,
                        "centroid_lon": 74.456,
                        "max_spread_m": 0.0,
                        "has_conflict": False,
                        "conflict_types": None,
                        "conflict_summary": None,
                    }])
                return MockResult([])

            # 4. Source records query
            if "SELECT source_id FROM resolved_entities" in sql:
                if target == "sample-multi-uuid":
                    return MockResult([{"source_id": "source_osm_123"}, {"source_id": "source_oa_456"}])
                return MockResult([{"source_id": target}])

            # 5. why_linked query
            if "why_linked(" in sql and "why_linked_summary" not in sql:
                if target == "sample-multi-uuid":
                    return MockResult([{
                        "entity_id": "sample-multi-uuid",
                        "id_a": "source_osm_123",
                        "name_a": "Sample Intl Airport",
                        "type_a": "commercial",
                        "icao_a": "VIXX",
                        "id_b": "source_oa_456",
                        "name_b": "Sample International",
                        "type_b": "commercial",
                        "icao_b": "VIXX",
                        "distance_m": 120.5,
                        "dist_score": 0.988,
                        "name_sim_score": 0.950,
                        "code_match_score": 1.0,
                        "type_compat_score": 1.0,
                        "weight_name": 0.35,
                        "weight_dist": 0.30,
                        "weight_code": 0.20,
                        "weight_type": 0.15,
                        "final_confidence": 0.978,
                        "band": "auto-merge",
                        "ruleset_version": "v1.0",
                        "reason_narrative": "Co-located high-confidence match with exact ICAO alignment.",
                        "decision_timestamp": "2026-11-21 12:00:00"
                    }])
                return MockResult([])

            # 6. why_linked_summary
            if "why_linked_summary(" in sql:
                return MockResult(scalar_val="AIRFIELD ENTITY RESOLUTION AUDIT REPORT\nEntity ID: sample-multi-uuid\nCLEAN MERGE")

            return MockResult([])

    return MockConnection()
