from __future__ import annotations

from typing import Any

from job_monitor.config import CompanyConfig, SourceType
from job_monitor.sources.ashby import AshbySource
from job_monitor.sources.greenhouse import GreenhouseSource
from job_monitor.sources.lever import LeverSource


class FakeHttpClient:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.urls.append(url)
        return self.payload


def _company(source_type: SourceType) -> CompanyConfig:
    return CompanyConfig(name="Example", source_type=source_type, ats_identifier="example")


def test_parse_greenhouse_response(fixture_json: Any) -> None:
    source = GreenhouseSource(FakeHttpClient(fixture_json("greenhouse_jobs.json")))  # type: ignore[arg-type]
    jobs = source.fetch_jobs(_company(SourceType.GREENHOUSE))
    assert len(jobs) == 2
    assert jobs[0].title == "Machine Learning Engineer, Evaluation"
    assert jobs[0].location == "Remote, United States"
    assert jobs[0].department == "AI"
    assert jobs[0].source_job_id == "101"


def test_parse_lever_response(fixture_json: Any) -> None:
    source = LeverSource(FakeHttpClient(fixture_json("lever_jobs.json")))  # type: ignore[arg-type]
    jobs = source.fetch_jobs(_company(SourceType.LEVER))
    assert len(jobs) == 1
    assert jobs[0].title == "Applied Scientist - Recommendations"
    assert jobs[0].location == "New York, NY"
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].date_posted is not None


def test_parse_ashby_response(fixture_json: Any) -> None:
    source = AshbySource(FakeHttpClient(fixture_json("ashby_jobs.json")))  # type: ignore[arg-type]
    jobs = source.fetch_jobs(_company(SourceType.ASHBY))
    assert len(jobs) == 1
    assert jobs[0].title == "AI Research Engineer"
    assert jobs[0].location == "San Francisco, California, United States"
    assert jobs[0].department == "Research"


def test_missing_fields_are_handled() -> None:
    source = AshbySource(FakeHttpClient({"jobs": [{"id": "1"}]}))  # type: ignore[arg-type]
    jobs = source.fetch_jobs(_company(SourceType.ASHBY))
    assert jobs[0].title == "Untitled role"
    assert jobs[0].location is None
