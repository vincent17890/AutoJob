from __future__ import annotations

from datetime import date
from typing import Any

from job_monitor.config import CompanyConfig
from job_monitor.http import HttpClient
from job_monitor.models import JobPosting


class AshbySource:
    source_name = "ashby"

    def __init__(self, http_client: HttpClient | None = None) -> None:
        self._http = http_client or HttpClient()

    def endpoint_for(self, company: CompanyConfig) -> str:
        if company.api_endpoint:
            return str(company.api_endpoint)
        return f"https://api.ashbyhq.com/posting-api/job-board/{company.ats_identifier}"

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        data = self._http.get_json(self.endpoint_for(company))
        raw_jobs = data.get("jobs", []) if isinstance(data, dict) else []
        return [
            self._parse_job(company, raw_job) for raw_job in raw_jobs if isinstance(raw_job, dict)
        ]

    def _parse_job(self, company: CompanyConfig, raw: dict[str, Any]) -> JobPosting:
        location = raw.get("location")
        if isinstance(location, dict):
            location_text = location.get("name")
        else:
            location_text = str(location) if location else None

        department = raw.get("department")
        if isinstance(department, dict):
            department_text = department.get("name")
        else:
            department_text = str(department) if department else None

        job_url = raw.get("jobUrl") or raw.get("job_url") or raw.get("externalLink")
        apply_url = raw.get("applyUrl") or raw.get("apply_url") or job_url

        return JobPosting(
            stable_job_id=raw.get("id"),
            company=company.name,
            title=str(raw.get("title") or "Untitled role"),
            location=location_text,
            employment_type=raw.get("employmentType") or raw.get("employment_type"),
            department=department_text,
            description=(
                raw.get("descriptionPlain") or raw.get("descriptionHtml") or raw.get("description")
            ),
            posting_url=job_url,
            application_url=apply_url,
            source=self.source_name,
            source_job_id=raw.get("id"),
            date_posted=_parse_date(raw.get("publishedDate") or raw.get("createdAt")),
        )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
