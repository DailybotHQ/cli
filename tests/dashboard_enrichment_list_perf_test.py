"""Tests for dashboard enrichment query params on list endpoints (CORE-2362)."""

from unittest.mock import MagicMock, patch

from dailybot_cli.api_client import DailyBotClient, _merge_dashboard_enrichment_query


def test_merge_dashboard_enrichment_query_serializes_csv_and_booleans() -> None:
    params: dict = {}
    _merge_dashboard_enrichment_query(
        params,
        labels=["uuid-a", "uuid-b"],
        featured=True,
        prioritize_featured=False,
    )
    assert params == {
        "labels": "uuid-a,uuid-b",
        "featured": "true",
        "prioritize_featured": "false",
    }


@patch.object(DailyBotClient, "_paginated_get")
@patch.object(DailyBotClient, "_request")
def test_list_forms_forwards_enrichment_params(
    _request: MagicMock,
    paginated_get: MagicMock,
) -> None:
    paginated_get.return_value = MagicMock(results=[], count=0, next=None, previous=None)
    client = DailyBotClient(api_url="https://api.test", token="tok")
    client.list_forms(
        labels=["label-1", "label-2"],
        featured=True,
        prioritize_featured=True,
        fetch_all=False,
        page=1,
    )
    call_kwargs = paginated_get.call_args.kwargs
    assert call_kwargs["params"]["labels"] == "label-1,label-2"
    assert call_kwargs["params"]["featured"] == "true"
    assert call_kwargs["params"]["prioritize_featured"] == "true"


@patch.object(DailyBotClient, "_paginated_get")
@patch.object(DailyBotClient, "_request")
def test_list_workflows_forwards_enrichment_params(
    _request: MagicMock,
    paginated_get: MagicMock,
) -> None:
    paginated_get.return_value = MagicMock(results=[], count=0, next=None, previous=None)
    client = DailyBotClient(api_url="https://api.test", token="tok")
    client.list_workflows(labels=["label-1"], fetch_all=False, page=1)
    assert paginated_get.call_args.kwargs["params"]["labels"] == "label-1"
