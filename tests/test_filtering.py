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
        location="San Jose, California, United States",
        description="Build LLM evaluation infrastructure.",
        source="greenhouse",
        source_job_id="1",
    )
    decision = evaluate_job(job, FilterConfig(locations=["San Jose"]), _company())
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


def test_generic_us_location_does_not_match_without_target_city() -> None:
    job = JobPosting(
        company="Example",
        title="Machine Learning Engineer",
        location="United States",
        description="Work on ML infrastructure.",
        source="greenhouse",
        source_job_id="1",
    )
    decision = evaluate_job(
        job,
        FilterConfig(locations=["United States", "San Jose", "Sunnyvale"]),
        _company(),
    )
    assert decision.matched is False
    assert "location did not match" in decision.reason


def test_multilocation_us_job_without_target_city_does_not_match() -> None:
    job = JobPosting(
        company="Example",
        title="AI Engineer",
        location=(
            "Arlington/Rosslyn, Virginia, United States; "
            "Atlanta, Georgia, United States; "
            "Austin, Texas, United States; "
            "Chicago, Illinois, United States"
        ),
        description="Build LLM model evaluation systems.",
        source="avature",
        source_job_id="1",
    )
    decision = evaluate_job(
        job,
        FilterConfig(locations=["United States", "San Jose", "Sunnyvale"]),
        _company(),
    )
    assert decision.matched is False
    assert "location did not match" in decision.reason
