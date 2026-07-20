from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlsplit

import httpx

from job_monitor.config import CompanyConfig
from job_monitor.models import JobPosting


class WorkdaySource:
    source_name = "workday"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        page_size: int = 20,
        max_pages: int = 25,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=20,
            follow_redirects=True,
        )
        self._page_size = page_size
        self._max_pages = max_pages

    def endpoint_for(self, company: CompanyConfig) -> str:
        if company.api_endpoint:
            return str(company.api_endpoint)
        host = company.extra.get("host")
        tenant = company.extra.get("tenant") or company.ats_identifier
        site = company.extra.get("site")
        if not host or not tenant or not site:
            raise ValueError(
                "Workday companies require api_endpoint or extra.host, extra.tenant, extra.site"
            )
        return f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        endpoint = self.endpoint_for(company)
        postings: list[dict[str, Any]] = []
        for page in range(self._max_pages):
            offset = page * self._page_size
            data = self._post_json(
                endpoint,
                {
                    "appliedFacets": {},
                    "limit": self._page_size,
                    "offset": offset,
                    "searchText": "",
                },
            )
            raw_postings = data.get("jobPostings", []) if isinstance(data, dict) else []
            postings.extend(item for item in raw_postings if isinstance(item, dict))
            total = (
                int(data.get("total", len(postings))) if isinstance(data, dict) else len(postings)
            )
            if len(postings) >= total or len(raw_postings) < self._page_size:
                break
        return [self._parse_job(company, endpoint, raw) for raw in postings]

    def _post_json(self, url: str, payload: dict[str, Any]) -> Any:
        response = self._client.post(url, json=payload, headers=_headers_for(url))
        response.raise_for_status()
        return response.json()

    def _parse_job(
        self,
        company: CompanyConfig,
        endpoint: str,
        raw: dict[str, Any],
    ) -> JobPosting:
        source_job_id = str(raw.get("bulletFields", [""])[0] or raw.get("id") or "").strip()
        external_path = raw.get("externalPath") or raw.get("jobPostingInfo", {}).get("externalUrl")
        posting_url = _posting_url(endpoint, str(external_path) if external_path else None)
        locations = raw.get("locationsText") or raw.get("locationsDisplay") or raw.get("location")

        return JobPosting(
            stable_job_id=source_job_id or None,
            company=company.name,
            title=str(raw.get("title") or "Untitled role"),
            location=str(locations) if locations else None,
            employment_type=_employment_type(raw),
            department=_department(raw),
            description=raw.get("jobDescription") or raw.get("jobDescriptionText"),
            posting_url=posting_url,
            application_url=posting_url,
            source=self.source_name,
            source_job_id=source_job_id or None,
            date_posted=_parse_posted_date(raw),
        )


def _posting_url(endpoint: str, external_path: str | None) -> str | None:
    if not external_path:
        return None
    host = endpoint.split("/wday/cxs/", 1)[0]
    return f"{host}{external_path}"


def _headers_for(url: str) -> dict[str, str]:
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": origin,
        "Referer": f"{origin}/",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }


def _employment_type(raw: dict[str, Any]) -> str | None:
    for field in raw.get("jobPostingInfo", {}).get("jobDescriptionFields", []):
        if not isinstance(field, dict):
            continue
        label = str(field.get("label") or "").casefold()
        if "time type" in label or "employment" in label:
            return str(field.get("text")) if field.get("text") else None
    return None


def _department(raw: dict[str, Any]) -> str | None:
    for key in ["jobFamily", "jobFamilyGroup", "department"]:
        if raw.get(key):
            return str(raw[key])
    return None


def _parse_posted_date(raw: dict[str, Any]) -> date | None:
    value = raw.get("postedOn") or raw.get("startDate")
    if not value:
        return None
    return _parse_workday_date_text(str(value), today=date.today())


def _parse_workday_date_text(text: str, *, today: date) -> date | None:
    normalized = " ".join(text.strip().casefold().split())
    if not normalized:
        return None

    if normalized in {"posted today", "today", "just posted"}:
        return today
    if normalized in {"posted yesterday", "yesterday"}:
        return today - timedelta(days=1)

    days_ago_match = re.fullmatch(r"posted (\d+)\+? days? ago", normalized)
    if days_ago_match:
        return today - timedelta(days=int(days_ago_match.group(1)))

    if normalized in {"posted 30+ days ago", "posted more than 30 days ago"}:
        return today - timedelta(days=30)

    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None
