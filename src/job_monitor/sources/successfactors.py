from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from job_monitor.config import CompanyConfig
from job_monitor.http import HttpClient
from job_monitor.models import JobPosting


class SuccessFactorsSource:
    source_name = "successfactors"

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
        if not company.careers_url:
            raise ValueError("SuccessFactors companies require api_endpoint or careers_url")
        company_id = company.ats_identifier or company.extra.get("company_id")
        if not company_id:
            raise ValueError(
                "SuccessFactors companies require ats_identifier or extra.company_id"
            )
        params = {
            "company": company_id,
            "career_ns": "job_listing_summary",
            "resultType": "XML",
        }
        locale = company.extra.get("locale")
        if locale:
            params["rcm_site_locale"] = str(locale)
        return _with_query(str(company.careers_url), params)

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        endpoint = self.endpoint_for(company)
        text = self._http.get_text(endpoint)
        if _looks_like_xml(text):
            return _parse_xml_jobs(text, company, self.source_name)
        return self._fetch_html_jobs(company, endpoint, text)

    def _fetch_html_jobs(
        self,
        company: CompanyConfig,
        first_page_url: str,
        first_page_html: str,
    ) -> list[JobPosting]:
        max_pages = int(company.extra.get("max_pages", self._max_pages))
        jobs_by_id: dict[str, JobPosting] = {}
        page_url = first_page_url
        page_html = first_page_html

        for page in range(max_pages):
            summaries = _parse_html_search_results(page_html, page_url)
            for summary in summaries:
                if summary.source_job_id in jobs_by_id:
                    continue
                detail_html = (
                    self._http.get_text(summary.url)
                    if company.extra.get("fetch_details", True)
                    else ""
                )
                job = _html_summary_to_job(summary, detail_html, company, self.source_name)
                key = job.source_job_id or job.deduplication_key or summary.url
                jobs_by_id.setdefault(key, job)
                jobs_by_id.setdefault(summary.source_job_id, job)

            next_url = _next_page_url(page_html, page_url)
            if not next_url or not summaries or page + 1 >= max_pages:
                break
            page_url = next_url
            page_html = self._http.get_text(page_url)

        jobs: list[JobPosting] = []
        seen_object_ids: set[int] = set()
        for job in jobs_by_id.values():
            object_id = id(job)
            if object_id not in seen_object_ids:
                jobs.append(job)
                seen_object_ids.add(object_id)
        return jobs


class _SuccessFactorsJobSummary:
    def __init__(
        self,
        *,
        source_job_id: str,
        title: str,
        location: str | None,
        url: str,
    ) -> None:
        self.source_job_id = source_job_id
        self.title = title
        self.location = location
        self.url = url


def _looks_like_xml(text: str) -> bool:
    stripped = text.lstrip()
    return stripped.startswith("<?xml") or bool(re.match(r"<(jobs|job|rss|feed)\b", stripped))


def _parse_xml_jobs(xml_text: str, company: CompanyConfig, source_name: str) -> list[JobPosting]:
    root = ET.fromstring(xml_text.strip())
    records = _job_records(root)
    jobs: list[JobPosting] = []
    for record in records:
        values = _flatten_record(record)
        title = _first(values, "title", "jobtitle", "job_title", "name") or "Untitled role"
        source_job_id = _first(
            values,
            "referencenumber",
            "reference_number",
            "reference",
            "id",
            "jobid",
            "job_id",
            "jobreqid",
            "requisitionid",
        )
        posting_url = _first(values, "url", "link", "joburl", "applyurl", "apply_url")
        location = _location(values)
        description = _clean_html(
            _first(values, "description", "jobdescription", "summary") or ""
        )

        jobs.append(
            JobPosting(
                stable_job_id=source_job_id,
                company=company.name,
                title=_clean_html(title),
                location=location,
                employment_type=_first(
                    values,
                    "employmenttype",
                    "employment_type",
                    "jobtype",
                    "job_type",
                    "type",
                ),
                department=_first(values, "department", "division", "category", "function"),
                description=description or None,
                posting_url=posting_url,
                application_url=posting_url,
                source=source_name,
                source_job_id=source_job_id,
                date_posted=_parse_date(_first(values, "date", "posteddate", "dateposted")),
            )
        )
    return jobs


def _parse_html_search_results(html: str, page_url: str) -> list[_SuccessFactorsJobSummary]:
    summaries: list[_SuccessFactorsJobSummary] = []
    seen_ids: set[str] = set()
    for row_match in re.finditer(
        r"<tr\b[^>]*class=[\"'][^\"']*data-row[^\"']*[\"'][^>]*>(?P<body>.*?)</tr>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        row = row_match.group("body")
        link_match = re.search(
            r"<a\b(?P<attrs>[^>]*class=[\"'][^\"']*jobTitle-link[^\"']*[\"'][^>]*)>"
            r"(?P<title>.*?)</a>",
            row,
            re.IGNORECASE | re.DOTALL,
        )
        if not link_match:
            continue
        href = _attr(link_match.group("attrs"), "href")
        if not href:
            continue
        source_job_id = _job_id_from_url(href)
        if not source_job_id or source_job_id in seen_ids:
            continue
        summaries.append(
            _SuccessFactorsJobSummary(
                source_job_id=source_job_id,
                title=_clean_html(link_match.group("title")),
                location=_html_location(row),
                url=urljoin(page_url, unescape(href)),
            )
        )
        seen_ids.add(source_job_id)
    return summaries


def _html_summary_to_job(
    summary: _SuccessFactorsJobSummary,
    detail_html: str,
    company: CompanyConfig,
    source_name: str,
) -> JobPosting:
    description_html = _job_description_html(detail_html)
    description = _clean_html_with_lines(description_html)
    return JobPosting(
        stable_job_id=summary.source_job_id,
        company=company.name,
        title=_detail_title(detail_html) or summary.title or "Untitled role",
        location=_detail_location(description) or summary.location,
        employment_type=_field_from_text(description, "Employment Type"),
        department=_field_from_text(description, "Work Area"),
        description=description or None,
        posting_url=summary.url,
        application_url=summary.url,
        source=source_name,
        source_job_id=_field_from_text(description, "Requisition ID") or summary.source_job_id,
        date_posted=_parse_date(_field_from_text(description, "Original Posting Date")),
    )


def _html_location(row: str) -> str | None:
    match = re.search(
        r"<td\b[^>]*class=[\"'][^\"']*colLocation[^\"']*[\"'][^>]*>(?P<body>.*?)</td>",
        row,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return _clean_html(match.group("body")) or None


def _job_description_html(html: str) -> str:
    match = re.search(
        r"<span\b[^>]*class=[\"'][^\"']*jobdescription[^\"']*[\"'][^>]*>(?P<body>.*?)</span>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group("body") if match else ""


def _detail_title(html: str) -> str | None:
    match = re.search(
        r"<span\b[^>]*itemprop=[\"']title[\"'][^>]*>(?P<title>.*?)</span>",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return _clean_html(match.group("title")) if match else None


def _detail_location(description: str) -> str | None:
    return _field_from_text(description, "Location")


def _field_from_text(text: str, label: str) -> str | None:
    pattern = rf"^{re.escape(label)}:\s*(?P<value>.+)$"
    for line in text.splitlines():
        match = re.search(pattern, line.strip())
        if match:
            value = match.group("value").strip()
            return value or None
    return None


def _next_page_url(html: str, page_url: str) -> str | None:
    current_startrow = int(dict(parse_qsl(urlsplit(page_url).query)).get("startrow", "0"))
    candidates: list[tuple[int, str]] = []
    for match in re.finditer(
        r"<a\b(?P<attrs>[^>]*href=[\"'][^\"']*startrow=\d+[^\"']*[\"'][^>]*)>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        href = _attr(match.group("attrs"), "href")
        if not href:
            continue
        absolute_url = urljoin(page_url, unescape(href))
        startrow = int(dict(parse_qsl(urlsplit(absolute_url).query)).get("startrow", "0"))
        if startrow > current_startrow:
            candidates.append((startrow, absolute_url))
    return min(candidates)[1] if candidates else None


def _job_id_from_url(url: str) -> str | None:
    match = re.search(r"/(\d+)(?:/)?$", unescape(urlsplit(url).path))
    return match.group(1) if match else None


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(
        rf"{re.escape(name)}\s*=\s*([\"'])(?P<value>.*?)\1",
        attrs,
        re.IGNORECASE | re.DOTALL,
    )
    return unescape(match.group("value")) if match else None


def _job_records(root: ET.Element) -> list[ET.Element]:
    named_records = [
        element
        for element in root.iter()
        if _tag_name(element.tag) in {"job", "item", "entry", "jobposting", "job_listing"}
    ]
    if named_records:
        return named_records

    children = list(root)
    if children and all(len(child) > 0 for child in children):
        return children
    return []


def _flatten_record(record: ET.Element) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for element in record.iter():
        key = _normalize_key(_tag_name(element.tag))
        text = _element_text(element)
        if key and text:
            values.setdefault(key, []).append(text)
    return values


def _element_text(element: ET.Element) -> str | None:
    text = " ".join(part.strip() for part in element.itertext() if part and part.strip())
    return unescape(text).strip() or None


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", key.casefold())


def _first(values: dict[str, list[str]], *keys: str) -> str | None:
    for key in keys:
        normalized_key = _normalize_key(key)
        items = values.get(normalized_key)
        if items:
            return items[0]
    return None


def _location(values: dict[str, list[str]]) -> str | None:
    locations = values.get("location")
    if locations:
        return "; ".join(dict.fromkeys(locations))
    parts = [
        _first(values, "city"),
        _first(values, "state", "region"),
        _first(values, "country"),
    ]
    return ", ".join(part for part in parts if part) or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    for parser in (_parse_iso_date, _parse_us_short_date, _parse_rfc_date):
        parsed = parser(text)
        if parsed:
            return parsed
    return None


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_rfc_date(value: str) -> date | None:
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, IndexError):
        return None


def _parse_us_short_date(value: str) -> date | None:
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", value)
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    year = int(match.group(3))
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _clean_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _clean_html_with_lines(value: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"</\s*(p|div|li|tr)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = [
        re.sub(r"\s+", " ", unescape(line)).strip()
        for line in text.splitlines()
        if line.strip()
    ]
    return "\n".join(lines)


def _with_query(url: str, params: dict[str, Any]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if value is not None})
    return urlunsplit(
        (parsed.scheme or "https", parsed.netloc, parsed.path or "/career", urlencode(query), "")
    )
