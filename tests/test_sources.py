from __future__ import annotations

from datetime import date
from typing import Any

from job_monitor.config import CompanyConfig, SourceType
from job_monitor.sources.ashby import AshbySource
from job_monitor.sources.avature import AvatureSource
from job_monitor.sources.eightfold import EightfoldSource
from job_monitor.sources.greenhouse import GreenhouseSource
from job_monitor.sources.icims import ICIMSSource
from job_monitor.sources.lever import LeverSource
from job_monitor.sources.smartrecruiters import SmartRecruitersSource
from job_monitor.sources.successfactors import SuccessFactorsSource
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


class FakeTextHttpClient:
    def __init__(self, pages: list[str]) -> None:
        self.pages = pages
        self.urls: list[str] = []

    def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.pages.pop(0)


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


def test_smartrecruiters_handles_string_ref_detail_url(fixture_json: Any) -> None:
    postings = fixture_json("smartrecruiters_postings.json")
    postings["content"][0]["ref"] = (
        "https://api.smartrecruiters.com/v1/companies/example/postings/743999999001"
    )
    source = SmartRecruitersSource(
        FakeSequenceHttpClient(  # type: ignore[arg-type]
            [
                postings,
                fixture_json("smartrecruiters_detail.json"),
                {"id": "743999999002", "name": "Sales Manager"},
            ]
        )
    )

    jobs = source.fetch_jobs(_company(SourceType.SMARTRECRUITERS))

    assert jobs[0].description
    assert "recommendation systems" in jobs[0].description


def test_smartrecruiters_constructs_individual_url_when_only_career_page_exists() -> None:
    source = SmartRecruitersSource(
        FakeSequenceHttpClient(  # type: ignore[arg-type]
            [
                {
                    "content": [
                        {
                            "id": "744000138739709",
                            "uuid": "9719ed66-7e64-4113-867e-578ee0bcdd23",
                            "name": "Electrical Engineer",
                            "postingUrl": "https://careers.smartrecruiters.com/BoschGroup",
                        }
                    ],
                    "totalFound": 1,
                }
            ]
        ),
        fetch_details=False,
    )
    company = CompanyConfig(
        name="Bosch",
        source_type=SourceType.SMARTRECRUITERS,
        ats_identifier="BoschGroup",
        careers_url="https://careers.smartrecruiters.com/BoschGroup",
    )

    jobs = source.fetch_jobs(company)

    assert jobs[0].posting_url == (
        "https://jobs.smartrecruiters.com/BoschGroup/744000138739709-electrical-engineer"
    )


def test_parse_eightfold_response(fixture_json: Any) -> None:
    source = EightfoldSource(
        FakeSequenceHttpClient(  # type: ignore[arg-type]
            [
                fixture_json("eightfold_search.json"),
                fixture_json("eightfold_detail.json"),
                {"data": {"id": 68758881875, "name": "Account Executive"}},
            ]
        )
    )
    company = CompanyConfig(
        name="Eightfold",
        source_type=SourceType.EIGHTFOLD,
        ats_identifier="eightfold.ai",
    )
    jobs = source.fetch_jobs(company)
    assert len(jobs) == 2
    assert jobs[0].title == "Staff Machine Learning Engineer - Agentic Models, LLM, RAG, GenAI"
    assert jobs[0].location == "Santa Clara, CA, US"
    assert jobs[0].department == "Engineering"
    assert jobs[0].source_job_id == "68761290831"
    assert jobs[0].posting_url == (
        "https://app.eightfold.ai/careers/job/68761290831?domain=eightfold.ai"
    )
    assert jobs[0].date_posted == date(2026, 5, 4)
    assert "AI agents" in (jobs[0].description or "")


def test_parse_icims_response(fixture_text: Any) -> None:
    source = ICIMSSource(
        FakeTextHttpClient(  # type: ignore[arg-type]
            [
                fixture_text("icims_search.html"),
                fixture_text("icims_detail.html"),
                fixture_text("icims_detail.html"),
            ]
        )
    )
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.ICIMS,
        ats_identifier="careers-example",
    )
    jobs = source.fetch_jobs(company)
    assert len(jobs) == 2
    assert jobs[0].title == "Machine Learning Engineer"
    assert jobs[0].location == "Santa Clara, CA, US"
    assert jobs[0].employment_type == "Full-Time"
    assert jobs[0].source_job_id == "1234"
    assert jobs[0].date_posted == date(2026, 7, 18)
    assert jobs[0].posting_url == (
        "https://careers-example.icims.com/jobs/1234/machine-learning-engineer/job"
    )
    assert "LLM retrieval" in (jobs[0].description or "")
    assert "in_iframe=1" in source.endpoint_for(company)


def test_parse_avature_response(fixture_text: Any) -> None:
    source = AvatureSource(
        FakeTextHttpClient(  # type: ignore[arg-type]
            [
                fixture_text("avature_search.html"),
                fixture_text("avature_search_page_2.html"),
                fixture_text("avature_detail.html"),
                fixture_text("avature_detail_missing_fields.html"),
                fixture_text("avature_detail_missing_fields.html"),
            ]
        )
    )
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.AVATURE,
        ats_identifier="example",
    )

    jobs = source.fetch_jobs(company)

    assert len(jobs) == 3
    assert jobs[0].title == "Machine Learning Engineer"
    assert jobs[0].location == "Menlo Park, CA, US"
    assert jobs[0].employment_type == "Full-Time"
    assert jobs[0].source_job_id == "REQ-12345"
    assert jobs[0].date_posted == date(2026, 7, 18)
    assert jobs[0].posting_url == (
        "https://example.avature.net/careers/JobDetail/"
        "United-States-Machine-Learning-Engineer/12345"
    )
    assert "LLM retrieval" in (jobs[0].description or "")


def test_parse_successfactors_response(fixture_text: Any) -> None:
    source = SuccessFactorsSource(
        FakeTextHttpClient([fixture_text("successfactors_jobs.xml")])  # type: ignore[arg-type]
    )
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.SUCCESSFACTORS,
        ats_identifier="example",
        careers_url="https://career4.successfactors.com/career",
    )

    jobs = source.fetch_jobs(company)

    assert len(jobs) == 2
    assert jobs[0].title == "Machine Learning Engineer, Recommendations"
    assert jobs[0].location == "San Jose, CA, US"
    assert jobs[0].employment_type == "Full Time"
    assert jobs[0].department == "Engineering"
    assert jobs[0].source_job_id == "SF-123"
    assert jobs[0].date_posted == date(2026, 7, 17)
    assert jobs[0].posting_url == (
        "https://career4.successfactors.com/career?career_ns=job_listing&"
        "company=example&navBarLevel=JOB_SEARCH&rcm_site_locale=en_US&career_job_req_id=9001"
    )
    assert "recommendation systems" in (jobs[0].description or "")


def test_successfactors_endpoint_uses_company_id_and_xml_feed() -> None:
    source = SuccessFactorsSource()
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.SUCCESSFACTORS,
        ats_identifier="example",
        careers_url="https://career4.successfactors.com/career",
        extra={"locale": "en_US"},
    )

    endpoint = source.endpoint_for(company)

    assert endpoint.startswith("https://career4.successfactors.com/career?")
    assert "company=example" in endpoint
    assert "career_ns=job_listing_summary" in endpoint
    assert "resultType=XML" in endpoint
    assert "rcm_site_locale=en_US" in endpoint


def test_successfactors_handles_missing_fields(fixture_text: Any) -> None:
    source = SuccessFactorsSource(
        FakeTextHttpClient([fixture_text("successfactors_missing_fields.xml")])  # type: ignore[arg-type]
    )
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.SUCCESSFACTORS,
        ats_identifier="example",
        careers_url="https://career4.successfactors.com/career",
    )

    jobs = source.fetch_jobs(company)

    assert jobs[0].title == "Untitled role"
    assert jobs[0].location is None
    assert jobs[0].source_job_id == "SF-125"


def test_parse_successfactors_html_search_response(fixture_text: Any) -> None:
    source = SuccessFactorsSource(
        FakeTextHttpClient(  # type: ignore[arg-type]
            [
                fixture_text("successfactors_search.html"),
                fixture_text("successfactors_detail.html"),
            ]
        )
    )
    company = CompanyConfig(
        name="SAP",
        source_type=SourceType.SUCCESSFACTORS,
        api_endpoint="https://jobs.sap.com/search/?q=&locationsearch=United%20States",
    )

    jobs = source.fetch_jobs(company)

    assert len(jobs) == 1
    assert jobs[0].title == "SAP SuccessFactors iXp Intern - AI Software Developer"
    assert jobs[0].location == "San Ramon, CA"
    assert jobs[0].employment_type == "Regular Full Time"
    assert jobs[0].department == "Software-Design and Development"
    assert jobs[0].source_job_id == "452056"
    assert jobs[0].date_posted == date(2026, 7, 17)
    assert jobs[0].posting_url == (
        "https://jobs.sap.com/job/San-Ramon-SAP-SuccessFactors-iXp-Intern-"
        "AI-Software-Developer-CA-94583/1413842633/"
    )
    assert "LLM evaluation" in (jobs[0].description or "")


def test_avature_accepts_careers_url_without_identifier() -> None:
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.AVATURE,
        careers_url="https://example.avature.net/careers/SearchJobs",
    )
    source = AvatureSource()
    assert source.endpoint_for(company) == "https://example.avature.net/careers/SearchJobs"


def test_avature_supports_query_job_id_detail_links(fixture_text: Any) -> None:
    source = AvatureSource(
        FakeTextHttpClient(  # type: ignore[arg-type]
            [
                fixture_text("avature_search_query_job_id.html"),
                fixture_text("avature_detail.html"),
            ]
        )
    )
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.AVATURE,
        careers_url="https://example.avature.net/careers/SearchJobs",
    )

    jobs = source.fetch_jobs(company)

    assert len(jobs) == 1
    assert jobs[0].source_job_id == "REQ-12345"
    assert jobs[0].posting_url == (
        "https://example.avature.net/careers/JobDetail/"
        "United-States-Machine-Learning-Engineer/12345"
    )


def test_avature_extracts_expanded_locations(fixture_text: Any) -> None:
    source = AvatureSource(
        FakeTextHttpClient(  # type: ignore[arg-type]
            [
                fixture_text("avature_search_query_job_id.html"),
                fixture_text("avature_detail_expanded_locations.html"),
            ]
        )
    )
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.AVATURE,
        careers_url="https://example.avature.net/careers/SearchJobs",
    )

    jobs = source.fetch_jobs(company)

    assert jobs[0].location == (
        "Arlington/Rosslyn, Virginia, United States; "
        "Austin, Texas, United States; "
        "San Jose, California, United States"
    )


def test_avature_extracts_div_label_fields(fixture_text: Any) -> None:
    source = AvatureSource(
        FakeTextHttpClient(  # type: ignore[arg-type]
            [
                fixture_text("avature_search_query_job_id.html"),
                fixture_text("avature_detail_div_fields.html"),
            ]
        )
    )
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.AVATURE,
        careers_url="https://example.avature.net/careers/SearchJobs",
    )

    jobs = source.fetch_jobs(company)

    assert jobs[0].location == "Taiwan"
    assert jobs[0].department == "Engineering"


def test_avature_uses_job_offset_pagination(fixture_text: Any) -> None:
    client = FakeTextHttpClient(
        [
            fixture_text("avature_search.html"),
            fixture_text("avature_search_page_2.html"),
            fixture_text("avature_detail.html"),
            fixture_text("avature_detail_missing_fields.html"),
            fixture_text("avature_detail_missing_fields.html"),
        ]
    )
    source = AvatureSource(client)  # type: ignore[arg-type]
    source.fetch_jobs(_company(SourceType.AVATURE))
    assert "jobOffset=2" in client.urls[1]


def test_avature_respects_company_max_pages(fixture_text: Any) -> None:
    client = FakeTextHttpClient(
        [
            fixture_text("avature_search.html"),
            fixture_text("avature_detail.html"),
            fixture_text("avature_detail_missing_fields.html"),
        ]
    )
    source = AvatureSource(client)  # type: ignore[arg-type]
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.AVATURE,
        careers_url="https://example.avature.net/careers/SearchJobs",
        extra={"max_pages": 1},
    )

    jobs = source.fetch_jobs(company)

    assert len(jobs) == 2
    assert all("jobOffset=" not in url for url in client.urls)


def test_smartrecruiters_uses_configured_country_filter(fixture_json: Any) -> None:
    client = FakeSequenceHttpClient([fixture_json("smartrecruiters_postings.json")])
    source = SmartRecruitersSource(client, fetch_details=False)  # type: ignore[arg-type]
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.SMARTRECRUITERS,
        ats_identifier="example",
        location_filters=["United States"],
    )
    source.fetch_jobs(company)
    assert "country=us" in client.urls[0]


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
