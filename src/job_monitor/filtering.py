from __future__ import annotations

from dataclasses import dataclass

from job_monitor.config import CompanyConfig, FilterConfig
from job_monitor.deduplication import normalize_text
from job_monitor.models import JobPosting, MatchStatus

_BROAD_LOCATION_FILTERS = {
    "united states",
    "usa",
    "us",
    "u s",
    "u s a",
    "remote",
    "hybrid",
    "california",
    "ca",
    "new york",
    "ny",
    "washington",
    "wa",
    "texas",
    "tx",
    "massachusetts",
    "ma",
}


@dataclass(frozen=True)
class FilterDecision:
    matched: bool
    matched_keywords: list[str]
    reason: str


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    normalized_text = normalize_text(text)
    return [keyword for keyword in keywords if normalize_text(keyword) in normalized_text]


def _specific_location_filters(location_filters: list[str]) -> list[str]:
    return [
        location_filter
        for location_filter in location_filters
        if normalize_text(location_filter) not in _BROAD_LOCATION_FILTERS
    ]


def _job_text(job: JobPosting) -> str:
    return " ".join(
        value
        for value in [
            job.title,
            job.description,
            job.department,
            job.location,
            job.employment_type,
        ]
        if value
    )


def evaluate_job(
    job: JobPosting,
    global_filters: FilterConfig,
    company: CompanyConfig,
) -> FilterDecision:
    title_keywords = company.title_keywords_include or global_filters.title_keywords
    description_keywords = (
        company.description_keywords_include or global_filters.description_keywords
    )
    excluded_keywords = global_filters.exclude_keywords + company.title_keywords_exclude
    if global_filters.allow_internships:
        excluded_keywords = [
            keyword
            for keyword in excluded_keywords
            if normalize_text(keyword) not in {"intern", "internship"}
        ]

    title_matches = _contains_any(job.title, title_keywords)
    description_matches = _contains_any(job.description or "", description_keywords)
    excluded_matches = _contains_any(_job_text(job), excluded_keywords)
    seniority_matches = _contains_any(job.title, global_filters.seniority_exclude)

    if excluded_matches:
        return FilterDecision(False, [], f"excluded keyword(s): {', '.join(excluded_matches)}")
    if seniority_matches:
        return FilterDecision(False, [], f"excluded seniority: {', '.join(seniority_matches)}")

    location_filters = company.location_filters or global_filters.locations
    location_text = job.location or ""
    specific_location_filters = _specific_location_filters(location_filters)
    location_matches = _contains_any(location_text, specific_location_filters)
    if location_filters and not location_matches:
        return FilterDecision(
            False,
            [],
            f"location did not match configured filters: {location_text}",
        )

    employment_filters = company.employment_types or global_filters.employment_types
    if employment_filters and job.employment_type:
        employment_matches = _contains_any(job.employment_type, employment_filters)
        if not employment_matches:
            return FilterDecision(
                False,
                [],
                f"employment type did not match: {job.employment_type}",
            )

    matched_keywords = list(dict.fromkeys(title_matches + description_matches))
    if not matched_keywords:
        return FilterDecision(False, [], "no configured title or description keywords matched")

    reasons = []
    if title_matches:
        reasons.append(f"title matched: {', '.join(title_matches)}")
    if description_matches:
        reasons.append(f"description matched: {', '.join(description_matches)}")
    if location_matches:
        reasons.append(f"location matched: {', '.join(location_matches)}")

    return FilterDecision(True, matched_keywords, "; ".join(reasons))


def apply_filter(
    job: JobPosting,
    global_filters: FilterConfig,
    company: CompanyConfig,
) -> JobPosting:
    decision = evaluate_job(job, global_filters, company)
    job.match_status = MatchStatus.MATCHED if decision.matched else MatchStatus.FILTERED_OUT
    job.matched_keywords = decision.matched_keywords
    job.match_reason = decision.reason
    return job
