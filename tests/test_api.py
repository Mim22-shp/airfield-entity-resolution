"""
Test suite for FastAPI endpoints:
- GET /
- GET /health
- GET /entity/{id}
- GET /entity/{id}/why (JSON structured breakdown)
- GET /entity/{id}/why?format=text (Formatted operational audit text)
- 404 validation for unknown entity IDs
- Singleton entity explanation
"""

import pytest
from api import app, get_db


def test_root_endpoint(client):
    """Verifies root endpoint returns service info and documentation links."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "title" in data
    assert data["docs_url"] == "/docs"


def test_health_endpoint(client):
    """Verifies /health endpoint returns health status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database_connected" in data


def test_entity_why_json_success(client, mock_db_session):
    """Tests /entity/{id}/why with a valid multi-record entity returning structured audit JSON."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    try:
        response = client.get("/entity/sample-multi-uuid/why")
        assert response.status_code == 200
        data = response.json()

        # Validate master entity summary
        assert data["target_id"] == "sample-multi-uuid"
        assert data["resolved_entity_id"] == "sample-multi-uuid"
        assert data["is_singleton"] is False
        assert len(data["records_merged"]) == 2
        assert "source_osm_123" in data["records_merged"]
        assert "source_oa_456" in data["records_merged"]

        # Validate entity metadata
        entity = data["entity"]
        assert entity["primary_name"] == "Sample International Airport"
        assert entity["canonical_icao"] == "VIXX"
        assert entity["canonical_iata"] == "SIA"
        assert entity["record_count"] == 2
        assert entity["has_conflict"] is False

        # Validate pairwise match evidence
        links = data["pairwise_links"]
        assert len(links) == 1
        link = links[0]
        assert link["id_a"] == "source_osm_123"
        assert link["id_b"] == "source_oa_456"
        assert link["final_confidence"] > 0.80
        assert link["band"] == "auto-merge"
        assert "weights" in link
        assert link["weights"]["name"] == 0.35
        assert link["weights"]["dist"] == 0.30

        # Validate explanation narrative
        assert "resolved from 2 source records" in data["explanation_narrative"]
    finally:
        app.dependency_overrides.clear()


def test_entity_why_by_source_id(client, mock_db_session):
    """Tests /entity/{id}/why when querying by a constituent source_id instead of entity UUID."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    try:
        response = client.get("/entity/source_osm_123/why")
        assert response.status_code == 200
        data = response.json()
        assert data["target_id"] == "source_osm_123"
        assert data["resolved_entity_id"] == "sample-multi-uuid"
        assert data["entity"]["canonical_icao"] == "VIXX"
    finally:
        app.dependency_overrides.clear()


def test_entity_why_text_format(client, mock_db_session):
    """Tests /entity/{id}/why?format=text returns plain-text operational audit report."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    try:
        response = client.get("/entity/sample-multi-uuid/why?format=text")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert "AIRFIELD ENTITY RESOLUTION AUDIT REPORT" in response.text
    finally:
        app.dependency_overrides.clear()


def test_entity_why_singleton(client, mock_db_session):
    """Tests explaining a singleton entity with no pairwise merge links."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    try:
        response = client.get("/entity/sample-singleton-uuid/why")
        assert response.status_code == 200
        data = response.json()
        assert data["is_singleton"] is True
        assert len(data["pairwise_links"]) == 0
        assert "singleton airfield containing 1 source record" in data["explanation_narrative"]
    finally:
        app.dependency_overrides.clear()


def test_entity_why_not_found(client, mock_db_session):
    """Tests /entity/{id}/why returns 404 for an unknown entity ID."""
    app.dependency_overrides[get_db] = lambda: mock_db_session
    try:
        response = client.get("/entity/non-existent-uuid-9999/why")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_live_db_sample_if_available(client):
    """Tests against real database if connected, ensuring live integration works."""
    health_resp = client.get("/health")
    if health_resp.json().get("database_connected"):
        entities_resp = client.get("/entities?limit=1")
        if entities_resp.status_code == 200 and len(entities_resp.json()) > 0:
            sample_id = entities_resp.json()[0]["entity_id"]
            why_resp = client.get(f"/entity/{sample_id}/why")
            assert why_resp.status_code == 200
            assert "explanation_narrative" in why_resp.json()
