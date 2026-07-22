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


class AvatureSource:
    source_name = "avature"

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
        if company.ats_identifier:
            return f"https://{company.ats_identifier}.avature.net/careers/SearchJobs"
        raise ValueError("Avature companies require careers_url, api_endpoint, or ats_identifier")

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        first_page_url = self.endpoint_for(company)
        max_pages = int(company.extra.get("max_pages", self._max_pages))
        summaries_by_id: dict[str, _AvatureJobSummary] = {}
        offset_param: str | None = None
        offset = 0

        for page in range(max_pages):
            page_url = (
                first_page_url if page == 0 else _with_query(first_page_url, {offset_param: offset})
            )
            html = self._http.get_text(page_url)
            page_summaries = _parse_search_results(html, page_url)
            if page == 0:
                offset_param = _offset_param(page_summaries)
            for summary in page_summaries:
                summaries_by_id.setdefault(summary.source_job_id, summary)
            if not page_summaries:
                break
            offset += len(page_summaries)
            if not _has_more_pages(html, offset):
                break

        return [self._parse_job(company, summary) for summary in summaries_by_id.values()]

    def _parse_job(self, company: CompanyConfig, summary: _AvatureJobSummary) -> JobPosting:
        detail_html = self._http.get_text(summary.url)
        job_data = _parse_json_ld_job(detail_html)

        title = str(
            job_data.get("title")
            or _meta_content(detail_html, "og:title")
            or _heading_text(detail_html)
            or summary.title
            or "Untitled role"
        )
        location = (
            _expanded_locations_text(detail_html)
            or _location_text(job_data.get("jobLocation"))
            or _field_text(
                detail_html,
                ["primary location", "job location", "location", "locations"],
            )
            or summary.location
        )
        description = (
            _description_text(job_data.get("description"))
            or _description_from_html(detail_html)
            or summary.description
        )
        posting_url = str(job_data.get("url") or summary.url)
        source_job_id = _identifier_text(job_data.get("identifier")) or summary.source_job_id

        return JobPosting(
            stable_job_id=source_job_id,
            company=company.name,
            title=_clean_html(title),
            location=location,
            employment_type=_employment_type(job_data.get("employmentType"))
            or _field_text(detail_html, ["employment type", "job type", "work type"]),
            department=_field_text(
                detail_html,
                ["business area", "business function", "department", "team", "category"],
            )
            or summary.department,
            description=description,
            posting_url=posting_url,
            application_url=posting_url,
            source=self.source_name,
            source_job_id=source_job_id,
            date_posted=_parse_date(job_data.get("datePosted")),
        )


def _expanded_locations_text(html: str) -> str | None:
    block = re.search(
        r"Same job available.*?(?=<section\b|<article\b|</header>|</body>)",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not block:
        return None
    locations = [
        _clean_html(item)
        for item in re.findall(
            r"<p\b[^>]*class=[\"'][^\"']*paragraph[^\"']*[\"'][^>]*>(.*?)</p>",
            block.group(0),
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    return "; ".join(location for location in locations if location) or None


class _AvatureJobSummary:
    def __init__(
        self,
        *,
        source_job_id: str,
        title: str,
        url: str,
        detail_kind: str,
        location: str | None = None,
        department: str | None = None,
        description: str | None = None,
    ) -> None:
        self.source_job_id = source_job_id
        self.title = title
        self.url = url
        self.detail_kind = detail_kind
        self.location = location
        self.department = department
        self.description = description


def _search_url(careers_url: str) -> str:
    parsed = urlsplit(careers_url)
    if "/SearchJobs" in parsed.path:
        return careers_url
    base_path = parsed.path.rstrip("/")
    path = f"{base_path}/SearchJobs" if base_path else "/careers/SearchJobs"
    return urlunsplit((parsed.scheme or "https", parsed.netloc, path, parsed.query, ""))


def _with_query(url: str, params: dict[str, Any]) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items() if key and value is not None})
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )


def _parse_search_results(html: str, page_url: str) -> list[_AvatureJobSummary]:
    summaries: list[_AvatureJobSummary] = []
    seen_ids: set[str] = set()
    for match in re.finditer(
        r"<a\b(?P<attrs>[^>]*?)>(?P<body>.*?)</a>",
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        attrs = match.group("attrs")
        href = _attr(attrs, "href")
        if not href:
            continue
        parsed = _parse_detail_link(href)
        if not parsed:
            continue
        source_job_id, detail_kind = parsed
        if source_job_id in seen_ids:
            continue
        title = _attr(attrs, "title") or _clean_html(match.group("body"))
        if not title:
            continue
        article_html = _enclosing_article(html, match.start(), match.end())
        summaries.append(
            _AvatureJobSummary(
                source_job_id=source_job_id,
                title=title,
                url=urljoin(page_url, unescape(href)),
                detail_kind=detail_kind,
                location=_article_footer_value(article_html, "icon-address"),
                department=_article_footer_value(article_html, "icon-tag"),
                description=_article_content_text(article_html),
            )
        )
        seen_ids.add(source_job_id)
    return summaries


def _parse_detail_link(href: str) -> tuple[str, str] | None:
    parsed = urlsplit(unescape(href))
    path = parsed.path
    match = re.search(r"/(?P<kind>JobDetail|FolderDetail)/[^/?#]+/(?P<id>\d+)(?:/)?$", path)
    if match:
        return match.group("id"), match.group("kind")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    job_id = query.get("jobId") or query.get("folderId")
    if job_id and re.search(r"/(?P<kind>JobDetail|FolderDetail)$", path):
        kind = "FolderDetail" if "folderId" in query else "JobDetail"
        return job_id, kind
    return None


def _offset_param(summaries: list[_AvatureJobSummary]) -> str:
    if any(summary.detail_kind == "FolderDetail" for summary in summaries):
        return "folderOffset"
    return "jobOffset"


def _enclosing_article(html: str, start: int, end: int) -> str:
    article_start = html.rfind("<article", 0, start)
    article_end = html.find("</article>", end)
    if article_start == -1 or article_end == -1:
        return ""
    return html[article_start : article_end + len("</article>")]


def _article_footer_value(article_html: str, icon_class: str) -> str | None:
    if not article_html:
        return None
    for paragraph in re.findall(
        r"<p\b[^>]*>(.*?)</p>",
        article_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        if icon_class in paragraph:
            return _clean_html(paragraph)
    return None


def _article_content_text(article_html: str) -> str | None:
    match = re.search(
        r"<div\b[^>]*class=[\"'][^\"']*article__content\b[^\"']*[\"'][^>]*>(.*?)</div>",
        article_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return _clean_html(match.group(1)) if match else None


def _has_more_pages(html: str, next_offset: int) -> bool:
    return (
        f"jobOffset={next_offset}" in html
        or f"jobOffset%3D{next_offset}" in html
        or f"folderOffset={next_offset}" in html
        or f"folderOffset%3D{next_offset}" in html
    )


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
        text = ", ".join(str(part) for part in parts if part)
        if text:
            return text
        return str(address.get("streetAddress")) if address.get("streetAddress") else None
    return None


def _country_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return str(value.get("name")) if value.get("name") else None
    return str(value) if value else None


def _employment_type(value: Any) -> str | None:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return str(value).replace("_", "-").title() if value else None


def _identifier_text(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ["value", "name", "@id"]:
            if value.get(key):
                return str(value[key])
        return None
    return str(value) if value else None


def _description_text(value: Any) -> str | None:
    return _clean_html(str(value)) if value else None


def _description_from_html(html: str) -> str | None:
    meta_description = _meta_content(html, "description")
    if meta_description:
        return _clean_html(meta_description)
    body_match = re.search(r"<body[^>]*>(.*?)</body>", html, re.IGNORECASE | re.DOTALL)
    return _clean_html(body_match.group(1)) if body_match else None


def _field_text(html: str, labels: list[str]) -> str | None:
    expected_labels = {label.casefold() for label in labels}
    for label, value in re.findall(
        r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>",
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        label_text = _clean_html(label).casefold()
        if label_text in expected_labels:
            value_text = _clean_html(value)
            return value_text[:200] if value_text else None

    for label, value in re.findall(
        (
            r"<div\b[^>]*class=[\"'][^\"']*article__content__view__field__label[^\"']*"
            r"[\"'][^>]*>(.*?)</div>\s*<div\b[^>]*class=[\"'][^\"']*"
            r"article__content__view__field__value[^\"']*[\"'][^>]*>(.*?)</div>"
        ),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        label_text = _clean_html(label).casefold()
        if label_text in expected_labels:
            value_text = _clean_html(value)
            return value_text[:200] if value_text else None

    text = _clean_html(html)
    for label in labels:
        pattern = rf"\b{re.escape(label)}\b\s*:\s+([^|•]+)"
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            return value[:200] if value else None
    return None


def _heading_text(html: str) -> str | None:
    match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    return _clean_html(match.group(1)) if match else None


def _meta_content(html: str, name: str) -> str | None:
    patterns = [
        rf"<meta[^>]+(?:name|property)=[\"']{re.escape(name)}[\"'][^>]+content=[\"']([^\"']+)[\"']",
        rf"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+(?:name|property)=[\"']{re.escape(name)}[\"']",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            return unescape(match.group(1)).strip()
    return None


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
    text = re.sub(r"<script\b.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(unescape(text).split())
