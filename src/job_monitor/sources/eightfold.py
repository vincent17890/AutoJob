from __future__ import annotations

from datetime import UTC, date, datetime
from html import unescape
from typing import Any
from urllib.parse import urlencode

from job_monitor.config import CompanyConfig
from job_monitor.http import HttpClient
from job_monitor.models import JobPosting


class EightfoldSource:
    source_name = "eightfold"

    def __init__(
        self,
        http_client: HttpClient | None = None,
        *,
        page_size: int = 10,
        max_pages: int = 25,
        fetch_details: bool = True,
    ) -> None:
        self._http = http_client or HttpClient()
        self._page_size = page_size
        self._max_pages = max_pages
        self._fetch_details = fetch_details

    def endpoint_for(self, company: CompanyConfig) -> str:
        if company.api_endpoint:
            return str(company.api_endpoint)
        return "https://app.eightfold.ai/api/pcsx/search"

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        endpoint = self.endpoint_for(company)
        domain = _domain_for(company)
        raw_positions: list[dict[str, Any]] = []

        for page in range(self._max_pages):
            start = page * self._page_size
            data = self._http.get_json(
                _with_query(
                    endpoint,
                    {
                        "domain": domain,
                        "query": company.extra.get("query", "*"),
                        "sort_by": company.extra.get("sort_by", "relevance"),
                        "start": start,
                    },
                )
            )
            payload = data.get("data", {}) if isinstance(data, dict) else {}
            positions = payload.get("positions", []) if isinstance(payload, dict) else []
            page_positions = [item for item in positions if isinstance(item, dict)]
            raw_positions.extend(page_positions)

            total = (
                int(payload.get("count", len(raw_positions))) if isinstance(payload, dict) else 0
            )
            if len(raw_positions) >= total or len(page_positions) < self._page_size:
                break

        return [self._parse_job(company, domain, raw) for raw in raw_positions]

    def _parse_job(
        self,
        company: CompanyConfig,
        domain: str,
        raw: dict[str, Any],
    ) -> JobPosting:
        fetch_details = bool(company.extra.get("fetch_details", self._fetch_details))
        details = self._details_for(domain, raw) if fetch_details else raw
        merged = {**raw, **details}
        source_job_id = str(merged.get("id") or merged.get("atsJobId") or "").strip()
        posting_url = _posting_url(domain, merged)

        return JobPosting(
            stable_job_id=source_job_id or None,
            company=company.name,
            title=str(merged.get("name") or "Untitled role"),
            location=_location_text(merged),
            employment_type=_employment_type(merged),
            department=str(merged.get("department")) if merged.get("department") else None,
            description=_description_text(merged),
            posting_url=posting_url,
            application_url=posting_url,
            source=self.source_name,
            source_job_id=source_job_id or None,
            date_posted=_parse_epoch_date(merged.get("postedTs") or merged.get("creationTs")),
        )

    def _details_for(self, domain: str, raw: dict[str, Any]) -> dict[str, Any]:
        position_id = raw.get("id") or raw.get("atsJobId")
        if not position_id:
            return raw
        data = self._http.get_json(
            _with_query(
                "https://app.eightfold.ai/api/pcsx/position_details",
                {
                    "domain": domain,
                    "position_id": position_id,
                },
            )
        )
        details = data.get("data", {}) if isinstance(data, dict) else {}
        return details if isinstance(details, dict) else raw


def _domain_for(company: CompanyConfig) -> str:
    if company.ats_identifier:
        return company.ats_identifier
    domain = company.extra.get("domain")
    if domain:
        return str(domain)
    raise ValueError("Eightfold companies require ats_identifier or extra.domain")


def _with_query(url: str, params: dict[str, Any]) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _posting_url(domain: str, raw: dict[str, Any]) -> str | None:
    position_url = raw.get("positionUrl")
    if position_url:
        return f"https://app.eightfold.ai{position_url}?domain={domain}"
    position_id = raw.get("id") or raw.get("atsJobId")
    if not position_id:
        return None
    return f"https://app.eightfold.ai/careers/job/{position_id}?domain={domain}"


def _location_text(raw: dict[str, Any]) -> str | None:
    locations = raw.get("standardizedLocations") or raw.get("locations")
    if isinstance(locations, list):
        return "; ".join(str(location) for location in locations if location) or None
    return str(locations) if locations else None


def _employment_type(raw: dict[str, Any]) -> str | None:
    value = raw.get("employmentType") or raw.get("employment_type")
    if value:
        return str(value)
    return "Full-time" if raw.get("isFullTime") else None


def _description_text(raw: dict[str, Any]) -> str | None:
    value = raw.get("jobDescription") or raw.get("description")
    return unescape(str(value)) if value else None


def _parse_epoch_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).date()
    except (TypeError, ValueError, OSError):
        return None
