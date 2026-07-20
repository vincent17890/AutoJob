from __future__ import annotations

from dataclasses import dataclass

from job_monitor.config import CompanyConfig, FilterConfig
from job_monitor.deduplication import normalize_text
from job_monitor.models import JobPosting, MatchStatus


@dataclass(frozen=True)
class FilterDecision:
    matched: bool
    matched_keywords: list[str]
    reason: str


def _contains_any(text: str, keywords: list[str]) -> list[str]:
    normalized_text = normalize_text(text)
    return [keyword for keyword in keywords if normalize_text(keyword) in normalized_text]


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
    location_matches = _contains_any(location_text, location_filters)
    is_remote = "remote" in normalize_text(location_text)
    location_allowed = location_matches or (global_filters.remote_allowed and is_remote)
    if location_filters and not location_allowed:
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
    elif is_remote:
        reasons.append("remote role allowed")

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
