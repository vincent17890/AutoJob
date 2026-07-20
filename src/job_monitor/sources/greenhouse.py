from __future__ import annotations

from datetime import date
from typing import Any

from job_monitor.config import CompanyConfig
from job_monitor.http import HttpClient
from job_monitor.models import JobPosting


class GreenhouseSource:
    source_name = "greenhouse"

    def __init__(self, http_client: HttpClient | None = None) -> None:
        self._http = http_client or HttpClient()

    def endpoint_for(self, company: CompanyConfig) -> str:
        if company.api_endpoint:
            return str(company.api_endpoint)
        return (
            f"https://boards-api.greenhouse.io/v1/boards/{company.ats_identifier}/jobs?content=true"
        )

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        data = self._http.get_json(self.endpoint_for(company))
        raw_jobs = data.get("jobs", []) if isinstance(data, dict) else []
        return [
            self._parse_job(company, raw_job) for raw_job in raw_jobs if isinstance(raw_job, dict)
        ]

    def _parse_job(self, company: CompanyConfig, raw: dict[str, Any]) -> JobPosting:
        location = raw.get("location") or {}
        departments = raw.get("departments") or []
        first_department = departments[0] if departments else {}
        source_job_id = str(raw.get("id") or "")
        absolute_url = raw.get("absolute_url")
        content = raw.get("content")
        updated_at = _parse_date(raw.get("updated_at"))

        return JobPosting(
            stable_job_id=source_job_id or None,
            company=company.name,
            title=str(raw.get("title") or "Untitled role"),
            location=location.get("name") if isinstance(location, dict) else None,
            employment_type=raw.get("metadata", {}).get("employment_type")
            if isinstance(raw.get("metadata"), dict)
            else None,
            department=first_department.get("name") if isinstance(first_department, dict) else None,
            description=str(content) if content else None,
            posting_url=absolute_url,
            application_url=absolute_url,
            source=self.source_name,
            source_job_id=source_job_id or None,
            date_posted=updated_at,
        )


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
