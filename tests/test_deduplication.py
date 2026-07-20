from __future__ import annotations

from job_monitor.deduplication import (
    generate_deduplication_key,
    normalize_location,
    normalize_title,
    normalize_url,
)


def test_title_normalization() -> None:
    assert normalize_title("Sr. ML Engineer — LLMs") == "senior ml engineer llms"


def test_location_normalization() -> None:
    assert normalize_location(" U.S.A. ") == "usa"


def test_url_normalization_removes_tracking_and_case() -> None:
    assert (
        normalize_url("HTTPS://Example.COM/jobs/123/?utm_source=x&gh_src=y&a=1")
        == "https://example.com/jobs/123?a=1"
    )


def test_deduplication_prefers_source_job_id() -> None:
    key = generate_deduplication_key(
        company="Example",
        source_job_id="ABC-123",
        application_url="https://example.com/a?utm_source=x",
        posting_url=None,
        title="Machine Learning Engineer",
        location="Remote",
    )
    assert key == "source:example:abc 123"


def test_deduplication_falls_back_to_title_location() -> None:
    key = generate_deduplication_key(
        company="Example",
        source_job_id=None,
        application_url=None,
        posting_url=None,
        title="Machine Learning Engineer",
        location="Remote, US",
    )
    assert key == "fallback:example:machine learning engineer:remote us"
