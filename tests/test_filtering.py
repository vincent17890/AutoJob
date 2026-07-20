from __future__ import annotations

from job_monitor.config import CompanyConfig, FilterConfig, SourceType
from job_monitor.filtering import evaluate_job
from job_monitor.models import JobPosting


def _company(**kwargs: object) -> CompanyConfig:
    return CompanyConfig(
        name="Example",
        source_type=SourceType.GREENHOUSE,
        ats_identifier="example",
        **kwargs,
    )


def test_keyword_filtering_matches_title_and_description() -> None:
    job = JobPosting(
        company="Example",
        title="Software Engineer, AI Agents",
        location="Remote, United States",
        description="Build LLM evaluation infrastructure.",
        source="greenhouse",
        source_job_id="1",
    )
    decision = evaluate_job(job, FilterConfig(), _company())
    assert decision.matched is True
    assert "software engineer" in decision.matched_keywords
    assert "title matched" in decision.reason


def test_excluded_keyword_blocks_match() -> None:
    job = JobPosting(
        company="Example",
        title="Machine Learning Engineer Internship",
        location="United States",
        description="Work on ML.",
        source="greenhouse",
        source_job_id="1",
    )
    decision = evaluate_job(job, FilterConfig(), _company())
    assert decision.matched is False
    assert "excluded keyword" in decision.reason


def test_location_filtering_blocks_non_us_role() -> None:
    job = JobPosting(
        company="Example",
        title="Machine Learning Engineer",
        location="Berlin, Germany",
        description="Work on ML infrastructure.",
        source="greenhouse",
        source_job_id="1",
    )
    decision = evaluate_job(job, FilterConfig(), _company())
    assert decision.matched is False
    assert "location did not match" in decision.reason
