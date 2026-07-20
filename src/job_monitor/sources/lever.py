from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from job_monitor.config import CompanyConfig
from job_monitor.http import HttpClient
from job_monitor.models import JobPosting


class LeverSource:
    source_name = "lever"

    def __init__(self, http_client: HttpClient | None = None) -> None:
        self._http = http_client or HttpClient()

    def endpoint_for(self, company: CompanyConfig) -> str:
        if company.api_endpoint:
            return str(company.api_endpoint)
        return f"https://api.lever.co/v0/postings/{company.ats_identifier}?mode=json"

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        data = self._http.get_json(self.endpoint_for(company))
        raw_jobs = data if isinstance(data, list) else data.get("postings", [])
        return [
            self._parse_job(company, raw_job) for raw_job in raw_jobs if isinstance(raw_job, dict)
        ]

    def _parse_job(self, company: CompanyConfig, raw: dict[str, Any]) -> JobPosting:
        categories = raw.get("categories") or {}
        lists = raw.get("lists") or []
        description_parts = [str(raw.get("descriptionPlain") or raw.get("description") or "")]
        if isinstance(lists, list):
            for item in lists:
                if isinstance(item, dict) and item.get("content"):
                    description_parts.append(str(item["content"]))

        hosted_url = raw.get("hostedUrl") or raw.get("hosted_url")
        apply_url = raw.get("applyUrl") or raw.get("apply_url") or hosted_url

        return JobPosting(
            stable_job_id=raw.get("id"),
            company=company.name,
            title=str(raw.get("text") or "Untitled role"),
            location=categories.get("location") if isinstance(categories, dict) else None,
            employment_type=categories.get("commitment") if isinstance(categories, dict) else None,
            department=categories.get("team") if isinstance(categories, dict) else None,
            description="\n".join(part for part in description_parts if part),
            posting_url=hosted_url,
            application_url=apply_url,
            source=self.source_name,
            source_job_id=raw.get("id"),
            date_posted=_parse_created_at(raw.get("createdAt")),
        )


def _parse_created_at(value: Any) -> date | None:
    if value is None:
        return None
    try:
        timestamp = int(value) / 1000
        return datetime.fromtimestamp(timestamp, UTC).date()
    except (TypeError, ValueError, OSError):
        return None
