from __future__ import annotations

from job_monitor.config import AppConfig, CompanyConfig, FilterConfig, SourceType
from job_monitor.models import JobPosting
from job_monitor.runner import run_monitor
from job_monitor.sheets import InMemorySheetStore
from job_monitor.sources.base import JobSource


class StaticSource:
    source_name = "static"

    def __init__(self, jobs: list[JobPosting]) -> None:
        self.jobs = jobs

    def endpoint_for(self, company: CompanyConfig) -> str:
        return f"memory://{company.key}"

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        return self.jobs


class FailingSource:
    source_name = "failing"

    def endpoint_for(self, company: CompanyConfig) -> str:
        return f"memory://{company.key}"

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        raise RuntimeError("boom")


def test_avoids_duplicate_sheet_rows() -> None:
    company = CompanyConfig(
        name="Example",
        source_type=SourceType.GREENHOUSE,
        ats_identifier="example",
    )
    job = JobPosting(
        company="Example",
        title="Machine Learning Engineer",
        location="Remote, United States",
        description="Build machine learning systems.",
        source="greenhouse",
        source_job_id="1",
    )
    config = AppConfig(filters=FilterConfig(), companies=[company])
    sheet = InMemorySheetStore(existing_keys={job.deduplication_key or ""})

    summary = run_monitor(
        config,
        sheet_store=sheet,
        sources={SourceType.GREENHOUSE: StaticSource([job])},
    )

    assert summary.jobs_matched == 1
    assert summary.new_jobs_inserted == 0
    assert summary.duplicates_skipped == 1
    assert sheet.jobs == []


def test_one_source_failure_does_not_stop_other_sources() -> None:
    failing = CompanyConfig(name="Bad", source_type=SourceType.GREENHOUSE, ats_identifier="bad")
    good = CompanyConfig(name="Good", source_type=SourceType.LEVER, ats_identifier="good")
    job = JobPosting(
        company="Good",
        title="Applied Scientist",
        location="United States",
        description="Machine learning research.",
        source="lever",
        source_job_id="2",
    )
    config = AppConfig(filters=FilterConfig(), companies=[failing, good])
    sheet = InMemorySheetStore()
    sources: dict[SourceType, JobSource] = {
        SourceType.GREENHOUSE: FailingSource(),
        SourceType.LEVER: StaticSource([job]),
    }

    summary = run_monitor(config, sheet_store=sheet, sources=sources)

    assert len(summary.failures) == 1
    assert summary.jobs_fetched == 1
    assert summary.new_jobs_inserted == 1
    assert len(sheet.jobs) == 1
