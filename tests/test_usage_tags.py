"""Cost-center and project-tag rollups (#484).

Tags are optional owner-assigned labels. They must appear in dashboards, the
JSON export and the bounded CSV export, while untagged rows stay valid and
group under ``untagged``. Tag data never crosses the user/workspace scope.
"""

import pytest

from app.services import usage_dashboards, usage_ledger


def _record(user, **kwargs):
    return usage_ledger.record_usage(
        source=kwargs.pop("source", "chat"),
        user=user,
        provider="mock",
        model="mock-1",
        cost_estimate=kwargs.pop("cost_estimate", 0.01),
        **kwargs,
    )


class TestTagNormalization:
    def test_empty_values_are_untagged(self):
        assert usage_ledger.normalize_tag(None) is None
        assert usage_ledger.normalize_tag("   ") is None

    def test_tags_are_trimmed_lowercased_and_collapsed(self):
        assert usage_ledger.normalize_tag("  R&D   Platform ") == "r&d platform"

    def test_over_long_and_control_character_tags_are_rejected(self):
        with pytest.raises(ValueError):
            usage_ledger.normalize_tag("x" * (usage_ledger.TAG_MAX_LENGTH + 1))
        with pytest.raises(ValueError):
            usage_ledger.normalize_tag("bad\x00tag")


class TestTagRollups:
    def test_dashboard_groups_tagged_and_untagged_rows(self, db, make_user):
        user = make_user(username="tag-owner", email="tag-owner@example.com")
        other = make_user(username="tag-other", email="tag-other@example.com")
        _record(user, cost_center=" R&D ", project_tag="Apollo", prompt_tokens=10)
        _record(user, cost_center="r&d", project_tag="apollo", prompt_tokens=5)
        _record(user, prompt_tokens=7)
        _record(other, cost_center="sales", project_tag="orion", prompt_tokens=99)

        payload = usage_dashboards.dashboard(user_id=user.id, days=30)

        centers = {row["cost_center"]: row for row in payload["by_cost_center"]}
        tags = {row["project_tag"]: row for row in payload["by_project_tag"]}
        assert set(centers) == {"r&d", usage_ledger.UNTAGGED_LABEL}
        assert centers["r&d"]["total_tokens"] == 15
        assert centers[usage_ledger.UNTAGGED_LABEL]["total_tokens"] == 7
        assert set(tags) == {"apollo", usage_ledger.UNTAGGED_LABEL}
        assert tags["apollo"]["total_tokens"] == 15
        assert tags[usage_ledger.UNTAGGED_LABEL]["total_tokens"] == 7

    def test_export_filters_by_tag_within_the_owner_scope(self, client, make_user, login):
        user = make_user(username="export-tag", email="export-tag@example.com")
        other = make_user(username="export-other", email="export-other@example.com")
        _record(user, cost_center="R&D", project_tag="Apollo", prompt_tokens=4)
        _record(user, cost_center="Ops", project_tag="Apollo", prompt_tokens=6)
        _record(other, cost_center="R&D", project_tag="Apollo", prompt_tokens=100)
        login(email="export-tag@example.com")

        response = client.get("/api/usage/export?cost_center=%20R%26D%20&project_tag=Apollo")

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["filters"]["cost_center"] == "r&d"
        assert payload["filters"]["project_tag"] == "apollo"
        assert payload["totals"]["count"] == 1
        assert payload["records"][0]["user_id"] == user.id
        assert payload["records"][0]["prompt_tokens"] == 4
        assert payload["records"][0]["cost_center"] == "r&d"
        assert payload["records"][0]["project_tag"] == "apollo"

    def test_csv_export_includes_tag_columns(self, client, make_user, login):
        user = make_user(username="csv-tag", email="csv-tag@example.com")
        _record(user, cost_center="R&D", project_tag="Apollo")
        _record(user)
        login(email="csv-tag@example.com")

        response = client.get("/billing/api/usage/dashboard.csv?days=7")

        assert response.status_code == 200
        lines = response.get_data(as_text=True).splitlines()
        assert "cost_center" in lines[0]
        assert "project_tag" in lines[0]
        assert any("r&d" in line and "apollo" in line for line in lines[1:])
