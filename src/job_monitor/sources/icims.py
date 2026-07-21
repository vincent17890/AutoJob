from __future__ import annotations

import json
import re
from datetime import date
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from job_monitor.config import CompanyConfig
from job_monitor.http import HttpClient
from job_monitor.models import JobPosting


class ICIMSSource:
    source_name = "icims"

    def __init__(
        self,
        http_client: HttpClient | None = None,
        *,
        max_pages: int = 25,
    ) -> None:
        self._http = http_client or HttpClient()
        self._max_pages = max_pages

    def endpoint_for(self, company: CompanyConfig) -> str:
        if company.api_endpoint:
            return str(company.api_endpoint)
        if company.careers_url:
            return _search_url(str(company.careers_url))
        host = _host_for(company)
        return f"https://{host}/jobs/search?ss=1&in_iframe=1"

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        first_page_url = self.endpoint_for(company)
        base_url = _base_url(first_page_url)
        summaries_by_id: dict[str, _ICIMSJobSummary] = {}

        for page in range(self._max_pages):
            page_url = _with_query(first_page_url, {"pr": page, "in_iframe": "1", "ss": "1"})
            html = self._http.get_text(page_url)
            page_summaries = _parse_search_results(html, base_url)
            for summary in page_summaries:
                summaries_by_id.setdefault(summary.source_job_id, summary)
            if not page_summaries or not _has_next_page(html, page):
                break

        return [self._parse_job(company, summary) for summary in summaries_by_id.values()]

    def _parse_job(self, company: CompanyConfig, summary: _ICIMSJobSummary) -> JobPosting:
        detail_html = self._http.get_text(_with_query(summary.url, {"in_iframe": "1"}))
        job_data = _parse_json_ld_job(detail_html)

        title = str(job_data.get("title") or summary.title or "Untitled role")
        location = _location_text(job_data.get("jobLocation")) or summary.location
        description = _description_text(job_data.get("description"))
        posting_url = str(job_data.get("url") or summary.url)

        return JobPosting(
            stable_job_id=summary.source_job_id,
            company=company.name,
            title=title,
            location=location,
            employment_type=_employment_type(job_data.get("employmentType")),
            department=summary.department,
            description=description,
            posting_url=posting_url,
            application_url=posting_url,
            source=self.source_name,
            source_job_id=summary.source_job_id,
            date_posted=_parse_date(job_data.get("datePosted")),
        )


class _ICIMSJobSummary:
    def __init__(
        self,
        *,
        source_job_id: str,
        title: str,
        url: str,
        location: str | None = None,
        department: str | None = None,
    ) -> None:
        self.source_job_id = source_job_id
        self.title = title
        self.url = url
        self.location = location
        self.department = department


def _host_for(company: CompanyConfig) -> str:
    identifier = (company.ats_identifier or "").strip()
    if not identifier:
        raise ValueError("iCIMS companies require careers_url, api_endpoint, or ats_identifier")
    if identifier.startswith(("http://", "https://")):
        return urlsplit(identifier).netloc
    if identifier.endswith(".icims.com"):
        return identifier
    return f"{identifier}.icims.com"


def _search_url(careers_url: str) -> str:
    parsed = urlsplit(careers_url)
    if "/jobs/search" in parsed.path:
        return _with_query(careers_url, {"ss": "1", "in_iframe": "1"})
    return urlunsplit(
        (
            parsed.scheme or "https",
            parsed.netloc,
            "/jobs/search",
            urlencode({"ss": "1", "in_iframe": "1"}),
            "",
        )
    )


def _base_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _with_query(url: str, params: dict[str, Any]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if value is not None})
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _parse_search_results(html: str, base_url: str) -> list[_ICIMSJobSummary]:
    summaries: list[_ICIMSJobSummary] = []
    seen_ids: set[str] = set()
    for match in re.finditer(
        r"<a\b(?P<attrs>[^>]*?)>(?P<body>.*?)</a>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        attrs = match.group("attrs")
        href = _attr(attrs, "href")
        if not href or not _is_job_link(href):
            continue
        source_job_id = _job_id_from_url(href)
        if not source_job_id or source_job_id in seen_ids:
            continue
        title = _attr(attrs, "title") or _clean_html(match.group("body"))
        if not title:
            continue
        url = urljoin(base_url, unescape(href))
        summaries.append(
            _ICIMSJobSummary(
                source_job_id=source_job_id,
                title=title,
                url=url,
            )
        )
        seen_ids.add(source_job_id)
    return summaries


def _is_job_link(href: str) -> bool:
    lowered = href.casefold()
    return (
        "/jobs/" in lowered
        and "/job" in lowered
        and "/login" not in lowered
        and "/referral" not in lowered
        and "mode=apply" not in lowered
    )


def _job_id_from_url(url: str) -> str | None:
    match = re.search(r"/jobs/(\d+)/", url)
    return match.group(1) if match else None


def _has_next_page(html: str, current_page: int) -> bool:
    return f"pr={current_page + 1}" in html or f"pr%3D{current_page + 1}" in html


def _parse_json_ld_job(html: str) -> dict[str, Any]:
    for script in re.findall(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        text = unescape(script).strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        job = _find_jobposting(payload)
        if job:
            return job
    return {}


def _find_jobposting(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        item_type = value.get("@type")
        if item_type == "JobPosting" or (isinstance(item_type, list) and "JobPosting" in item_type):
            return value
        graph = value.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                found = _find_jobposting(item)
                if found:
                    return found
    if isinstance(value, list):
        for item in value:
            found = _find_jobposting(item)
            if found:
                return found
    return None


def _location_text(value: Any) -> str | None:
    if isinstance(value, list):
        locations = [_location_text(item) for item in value]
        return "; ".join(location for location in locations if location) or None
    if not isinstance(value, dict):
        return str(value) if value else None
    address = value.get("address")
    if isinstance(address, dict):
        parts = [
            address.get("addressLocality"),
            address.get("addressRegion"),
            _country_name(address.get("addressCountry")),
        ]
        return ", ".join(str(part) for part in parts if part) or None
    return None


def _country_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return str(value.get("name")) if value.get("name") else None
    return str(value) if value else None


def _employment_type(value: Any) -> str | None:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return str(value).replace("_", "-").title() if value else None


def _description_text(value: Any) -> str | None:
    return _clean_html(str(value)) if value else None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(rf'{name}\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else None


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(text).split())
