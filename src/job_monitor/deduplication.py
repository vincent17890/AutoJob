from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_PARAMS = {"gh_src", "lever-source", "source", "ref", "referrer"}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.casefold()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_title(value: str | None) -> str:
    text = normalize_text(value)
    seniority_noise = {
        "sr": "senior",
        "swe": "software engineer",
    }
    return " ".join(seniority_noise.get(part, part) for part in text.split())


def normalize_location(value: str | None) -> str:
    text = normalize_text(value)
    replacements = {
        "u s": "us",
        "u s a": "usa",
        "united states of america": "united states",
    }
    return replacements.get(text, text)


def normalize_url(value: str | None) -> str:
    if not value:
        return ""
    parts = urlsplit(value.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = re.sub(r"/+", "/", parts.path).rstrip("/")
    query_items = []
    for key, item_value in parse_qsl(parts.query, keep_blank_values=True):
        lowered_key = key.lower()
        if lowered_key in TRACKING_QUERY_PARAMS:
            continue
        if any(lowered_key.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, item_value))
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def generate_deduplication_key(
    *,
    company: str,
    source_job_id: str | None,
    application_url: str | None,
    posting_url: str | None,
    title: str | None,
    location: str | None,
) -> str:
    normalized_company = normalize_text(company)
    if source_job_id:
        return f"source:{normalized_company}:{normalize_text(source_job_id)}"

    normalized_application_url = normalize_url(application_url)
    normalized_posting_url = normalize_url(posting_url)
    if normalized_application_url:
        return f"url:{short_hash(normalized_application_url)}"
    if normalized_posting_url:
        return f"url:{short_hash(normalized_posting_url)}"

    normalized_title = normalize_title(title)
    normalized_location = normalize_location(location)
    return f"fallback:{normalized_company}:{normalized_title}:{normalized_location}"
