from __future__ import annotations

from datetime import date
from typing import Any

from job_monitor.config import CompanyConfig, SourceType
from job_monitor.sources.ashby import AshbySource
from job_monitor.sources.greenhouse import GreenhouseSource
from job_monitor.sources.lever import LeverSource
from job_monitor.sources.smartrecruiters import SmartRecruitersSource
from job_monitor.sources.workday import WorkdaySource, _parse_workday_date_text, _posting_url


class FakeHttpClient:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.urls.append(url)
        return self.payload


class FakeSequenceHttpClient:
    def __init__(self, payloads: list[Any]) -> None:
        self.payloads = payloads
        self.urls: list[str] = []

    def get_json(self, url: str) -> Any:
        self.urls.append(url)
        return self.payloads.pop(0)


class FakeWorkdayClient:
    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def post(
        self,
        url: str,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> Any:
        self.posts.append((url, json))
        return FakeResponse(self.payload)


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
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


def test_parse_smartrecruiters_response(fixture_json: Any) -> None:
    source = SmartRecruitersSource(
        FakeSequenceHttpClient(  # type: ignore[arg-type]
            [
                fixture_json("smartrecruiters_postings.json"),
                fixture_json("smartrecruiters_detail.json"),
                {"id": "743999999002", "name": "Sales Manager"},
            ]
        )
    )
    jobs = source.fetch_jobs(_company(SourceType.SMARTRECRUITERS))
    assert len(jobs) == 2
    assert jobs[0].title == "Machine Learning Engineer, Recommendations"
    assert jobs[0].location == "San Jose, CA, us"
    assert jobs[0].employment_type == "Full-time"
    assert jobs[0].department == "Engineering"
    assert jobs[0].source_job_id == "11111111-2222-3333-4444-555555555555"
    assert jobs[0].date_posted == date(2026, 7, 18)
    assert jobs[0].posting_url == (
        "https://jobs.smartrecruiters.com/Example/"
        "743999999001-machine-learning-engineer-recommendations"
    )
    assert "recommendation systems" in (jobs[0].description or "")


def test_parse_workday_response(fixture_json: Any) -> None:
    source = WorkdaySource(
        FakeWorkdayClient(fixture_json("workday_jobs.json")),  # type: ignore[arg-type]
        page_size=100,
    )
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.WORKDAY,
        ats_identifier="example",
        careers_url="https://example.wd1.myworkdayjobs.com/External",
        api_endpoint="https://example.wd1.myworkdayjobs.com/wday/cxs/example/External/jobs",
    )
    jobs = source.fetch_jobs(company)
    assert len(jobs) == 2
    assert jobs[0].title == "Machine Learning Engineer, Inference"
    assert jobs[0].location == "US, CA, Santa Clara"
    assert jobs[0].employment_type == "Full time"
    assert jobs[0].department == "Engineering"
    assert jobs[0].source_job_id == "JR123"
    assert (
        jobs[0].posting_url
        == "https://example.wd1.myworkdayjobs.com/External/job/US-CA-Santa-Clara/Machine-Learning-Engineer_JR123"
    )


def test_build_workday_posting_url_from_careers_url() -> None:
    assert (
        _posting_url(
            "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
            "/job/US-CA-Santa-Clara/Machine-Learning-Engineer_JR123",
        )
        == "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA-Santa-Clara/Machine-Learning-Engineer_JR123"
    )
    assert (
        _posting_url(
            "https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap",
            "/job/Los-Angeles-California/Design-Engineer_R0046158-1",
        )
        == "https://wd1.myworkdaysite.com/en-US/recruiting/snapchat/snap/job/Los-Angeles-California/Design-Engineer_R0046158-1"
    )
    assert (
        _posting_url(
            "https://example.wd1.myworkdayjobs.com/External",
            "https://example.com/job/123",
        )
        == "https://example.com/job/123"
    )


def test_parse_workday_relative_posted_dates() -> None:
    today = date(2026, 7, 20)
    assert _parse_workday_date_text("Posted Today", today=today) == today
    assert _parse_workday_date_text("Posted Yesterday", today=today) == date(2026, 7, 19)
    assert _parse_workday_date_text("Posted 10 Days Ago", today=today) == date(2026, 7, 10)
    assert _parse_workday_date_text("Posted 1 Day Ago", today=today) == date(2026, 7, 19)
    assert _parse_workday_date_text("Posted 30+ Days Ago", today=today) == date(2026, 6, 20)
    assert _parse_workday_date_text("2026-07-18", today=today) == date(2026, 7, 18)
    assert _parse_workday_date_text("not a date", today=today) is None


def test_missing_fields_are_handled() -> None:
    source = AshbySource(FakeHttpClient({"jobs": [{"id": "1"}]}))  # type: ignore[arg-type]
    jobs = source.fetch_jobs(_company(SourceType.ASHBY))
    assert jobs[0].title == "Untitled role"
    assert jobs[0].location is None
