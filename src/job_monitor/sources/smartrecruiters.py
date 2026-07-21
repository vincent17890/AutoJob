from __future__ import annotations

from datetime import date
from html import unescape
from typing import Any
from urllib.parse import urlencode

from job_monitor.config import CompanyConfig
from job_monitor.http import HttpClient
from job_monitor.models import JobPosting


class SmartRecruitersSource:
    source_name = "smartrecruiters"

    def __init__(
        self,
        http_client: HttpClient | None = None,
        *,
        page_size: int = 100,
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
        return f"https://api.smartrecruiters.com/v1/companies/{company.ats_identifier}/postings"

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        base_endpoint = self.endpoint_for(company)
        raw_postings: list[dict[str, Any]] = []

        for page in range(self._max_pages):
            offset = page * self._page_size
            url = _with_query(
                base_endpoint,
                {
                    "limit": self._page_size,
                    "offset": offset,
                    "destination": "PUBLIC",
                    **_configured_query_params(company),
                },
            )
            data = self._http.get_json(url)
            content = data.get("content", []) if isinstance(data, dict) else []
            page_postings = [item for item in content if isinstance(item, dict)]
            raw_postings.extend(page_postings)

            total = (
                int(data.get("totalFound", len(raw_postings)))
                if isinstance(data, dict)
                else len(raw_postings)
            )
            if len(raw_postings) >= total or len(page_postings) < self._page_size:
                break

        return [self._parse_job(company, raw) for raw in raw_postings]

    def _parse_job(self, company: CompanyConfig, raw: dict[str, Any]) -> JobPosting:
        fetch_details = bool(company.extra.get("fetch_details", self._fetch_details))
        details = self._details_for(company, raw) if fetch_details else raw
        merged = {**raw, **details}
        source_job_id = str(merged.get("uuid") or merged.get("id") or "").strip()
        posting_url = (
            merged.get("jobAdUrl")
            or merged.get("postingUrl")
            or merged.get("url")
            or _career_posting_url(company, merged)
        )
        application_url = merged.get("applyUrl") or posting_url

        return JobPosting(
            stable_job_id=source_job_id or None,
            company=company.name,
            title=str(merged.get("name") or merged.get("title") or "Untitled role"),
            location=_location_text(merged.get("location")),
            employment_type=_label(merged.get("typeOfEmployment")),
            department=_label(merged.get("department")) or _label(merged.get("function")),
            description=_description_text(merged),
            posting_url=str(posting_url) if posting_url else None,
            application_url=str(application_url) if application_url else None,
            source=self.source_name,
            source_job_id=source_job_id or None,
            date_posted=_parse_date(merged.get("releasedDate") or merged.get("postedDate")),
        )

    def _details_for(self, company: CompanyConfig, raw: dict[str, Any]) -> dict[str, Any]:
        detail_url = _detail_url(self.endpoint_for(company), raw)
        if not detail_url:
            return raw
        detail = self._http.get_json(detail_url)
        return detail if isinstance(detail, dict) else raw


def _with_query(url: str, params: dict[str, Any]) -> str:
    params = {key: value for key, value in params.items() if value is not None}
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(params)}"


def _configured_query_params(company: CompanyConfig) -> dict[str, str]:
    params = {}
    country = company.extra.get("country")
    region = company.extra.get("region")
    city = company.extra.get("city")

    if not country and _has_us_location_filter(company):
        country = "us"

    if country:
        params["country"] = str(country)
    if region:
        params["region"] = str(region)
    if city:
        params["city"] = str(city)
    return params


def _has_us_location_filter(company: CompanyConfig) -> bool:
    normalized_filters = {item.strip().casefold() for item in company.location_filters}
    return bool(normalized_filters & {"united states", "us", "usa"})


def _detail_url(base_endpoint: str, raw: dict[str, Any]) -> str | None:
    ref = raw.get("ref")
    if isinstance(ref, dict) and ref.get("url"):
        return str(ref["url"])
    posting_id = raw.get("uuid") or raw.get("id")
    if not posting_id:
        return None
    return f"{base_endpoint.rstrip('/')}/{posting_id}"


def _career_posting_url(company: CompanyConfig, raw: dict[str, Any]) -> str | None:
    if not company.careers_url:
        return None
    posting_id = raw.get("id") or raw.get("uuid")
    if not posting_id:
        return None
    title_slug = str(raw.get("name") or raw.get("title") or "job").lower()
    title_slug = "-".join("".join(char if char.isalnum() else " " for char in title_slug).split())
    return f"{str(company.careers_url).rstrip('/')}/{posting_id}-{title_slug}"


def _label(value: Any) -> str | None:
    if isinstance(value, dict):
        return str(value["label"]) if value.get("label") else None
    return str(value) if value else None


def _location_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return str(value) if value else None

    parts = [
        value.get("city"),
        value.get("region"),
        value.get("country"),
    ]
    text = ", ".join(str(part) for part in parts if part)
    if value.get("remote"):
        text = f"{text} (Remote)" if text else "Remote"
    return text or None


def _description_text(raw: dict[str, Any]) -> str | None:
    job_ad = raw.get("jobAd")
    if isinstance(job_ad, dict):
        sections = [
            job_ad.get("companyDescription"),
            job_ad.get("jobDescription"),
            job_ad.get("qualifications"),
            job_ad.get("additionalInformation"),
        ]
        text = "\n".join(str(section) for section in sections if section)
        return unescape(text) if text else None

    return str(raw.get("description")) if raw.get("description") else None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
