"""Tests for the bounded JSON usage export (#455)."""

from datetime import datetime

from app.extensions import db
from app.models import Project, UsageRecord, Workspace
from app.models.project import SOURCE_ARCHIVE, STATUS_READY
from app.services import usage_ledger


def _setup(make_user, login):
    user = make_user(username="export-user", email="export@example.com")
    other = make_user(username="export-other", email="export-other@example.com")
    login(email="export@example.com")
    workspace = Workspace(user_id=user.id, name="Export workspace")
    db.session.add(workspace)
    db.session.commit()
    project = Project(
        workspace_id=workspace.id,
        user_id=user.id,
        name="Export project",
        source=SOURCE_ARCHIVE,
        status=STATUS_READY,
    )
    db.session.add(project)
    db.session.commit()
    return user, other, workspace, project


def _record(user, **kwargs):
    return usage_ledger.record_usage(
        source=kwargs.pop("source", "chat"),
        user=user,
        provider="mock",
        model="mock-1",
        **kwargs,
    )


class TestUsageExportApi:
    def test_requires_authentication(self, client):
        response = client.get("/api/usage/export")

        assert response.status_code == 401
        assert response.mimetype == "application/problem+json"

    def test_paginates_and_scopes_to_the_current_user(self, client, db, make_user, login):
        user, other, _, _ = _setup(make_user, login)
        _record(user, prompt_tokens=1)
        _record(user, prompt_tokens=2)
        _record(user, prompt_tokens=3)
        _record(other, prompt_tokens=999)

        response = client.get("/api/usage/export?page=2&limit=2")

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["schema_version"] == usage_ledger.EXPORT_SCHEMA_VERSION
        assert datetime.fromisoformat(payload["exported_at"])
        assert payload["filters"] == {
            "workspace_id": None,
            "project_id": None,
            "source": None,
            "cost_center": None,
            "project_tag": None,
        }
        assert payload["pagination"] == {
            "page": 2,
            "limit": 2,
            "max_limit": usage_ledger.EXPORT_MAX_LIMIT,
            "total": 3,
            "pages": 2,
            "has_next": False,
            "has_prev": True,
        }
        assert payload["totals"]["count"] == 3
        assert payload["totals"]["total_tokens"] == 6
        assert payload["page_totals"]["count"] == 1
        assert len(payload["records"]) == 1
        assert payload["currency"]["code"] == "USD"
        assert payload["cost_is_estimate"] is True
        assert payload["records"][0]["user_id"] == user.id
        assert payload["records"][0]["id"] == usage_ledger.query_records(user_id=user.id)[2].id
        assert all(record["user_id"] == user.id for record in payload["records"])

    def test_filters_by_workspace_project_and_source(self, client, db, make_user, login):
        user, _, workspace, project = _setup(make_user, login)
        _record(user, source="chat", workspace=workspace, prompt_tokens=1)
        _record(
            user,
            source="analysis",
            workspace=workspace,
            project=project,
            prompt_tokens=2,
        )
        _record(user, source="analysis", prompt_tokens=4)
        _record(user, source="review", prompt_tokens=8)

        workspace_payload = client.get(f"/api/usage/export?workspace_id={workspace.id}").get_json()
        assert workspace_payload["totals"]["count"] == 2
        assert workspace_payload["totals"]["total_tokens"] == 3
        assert workspace_payload["filters"]["workspace_id"] == workspace.id
        assert all(
            record["workspace_id"] == workspace.id for record in workspace_payload["records"]
        )

        project_payload = client.get(f"/api/usage/export?project_id={project.id}").get_json()
        assert project_payload["totals"]["count"] == 1
        assert project_payload["records"][0]["source"] == "analysis"

        source_payload = client.get("/api/usage/export?source=%20ANALYSIS%20").get_json()
        assert source_payload["totals"]["count"] == 2
        assert source_payload["filters"]["source"] == "analysis"
        assert all(record["source"] == "analysis" for record in source_payload["records"])

    def test_filters_cannot_escape_the_user_scope(self, client, db, make_user, login):
        user, other, workspace, _ = _setup(make_user, login)
        _record(other, workspace=workspace, prompt_tokens=50)
        _record(user, prompt_tokens=5)

        payload = client.get(f"/api/usage/export?workspace_id={workspace.id}").get_json()

        assert payload["totals"]["count"] == 0
        assert payload["records"] == []

    def test_invalid_page_and_limit_are_clamped(self, client, db, make_user, login):
        user, _, _, _ = _setup(make_user, login)
        _record(user, prompt_tokens=1)

        low = client.get("/api/usage/export?page=0&limit=0").get_json()
        assert low["pagination"]["page"] == 1
        assert low["pagination"]["limit"] == 1
        assert len(low["records"]) == 1

        high = client.get("/api/usage/export?page=-4&limit=9999").get_json()
        assert high["pagination"]["page"] == 1
        assert high["pagination"]["limit"] == usage_ledger.EXPORT_MAX_LIMIT

        invalid = client.get("/api/usage/export?page=abc&limit=abc").get_json()
        assert invalid["pagination"]["page"] == 1
        assert invalid["pagination"]["limit"] == usage_ledger.EXPORT_DEFAULT_LIMIT

    def test_beyond_last_page_is_empty_but_reports_totals(self, client, db, make_user, login):
        user, _, _, _ = _setup(make_user, login)
        _record(user, prompt_tokens=1)

        payload = client.get("/api/usage/export?page=9&limit=10").get_json()

        assert payload["records"] == []
        assert payload["pagination"]["total"] == 1
        assert payload["pagination"]["pages"] == 1
        assert payload["pagination"]["has_prev"] is True
        assert payload["pagination"]["has_next"] is False

    def test_record_shape_reuses_the_ledger_serializer(self, client, db, make_user, login):
        user, _, _, _ = _setup(make_user, login)
        record = _record(
            user,
            prompt_tokens=10,
            completion_tokens=5,
            latency_ms=12,
            status="SUCCESS",
            request_id="req-export",
        )

        payload = client.get("/api/usage/export").get_json()

        assert payload["records"] == [record.to_dict()]
        assert set(payload["records"][0]) == set(UsageRecord(id=1, source="chat").to_dict())
        assert payload["records"][0]["cost_estimate"] is not None
        assert "content" not in payload["records"][0]
