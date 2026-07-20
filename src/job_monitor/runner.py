from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from datetime import UTC, datetime

from job_monitor.config import AppConfig, CompanyConfig, SourceType
from job_monitor.filtering import apply_filter
from job_monitor.models import CompanyRunResult, MatchStatus, RunSummary
from job_monitor.sheets import SheetStore
from job_monitor.sources.base import JobSource
from job_monitor.sources.registry import build_source_registry

logger = logging.getLogger(__name__)


def run_monitor(
    config: AppConfig,
    *,
    sheet_store: SheetStore | None,
    dry_run: bool = False,
    company_key: str | None = None,
    sources: Mapping[SourceType, JobSource] | None = None,
) -> RunSummary:
    started = time.monotonic()
    source_registry = sources or build_source_registry()
    companies = _select_companies(config, company_key)
    existing_keys = (
        set() if dry_run or sheet_store is None else sheet_store.existing_deduplication_keys()
    )
    new_jobs_to_insert = []
    summary = RunSummary(companies_checked=len(companies))

    for company in companies:
        adapter = source_registry[company.source_type]
        endpoint = adapter.endpoint_for(company)
        company_result = CompanyRunResult(
            company=company.name,
            adapter=adapter.source_name,
            endpoint=endpoint,
        )
        try:
            logger.info(
                "fetching company jobs",
                extra={
                    "company": company.name,
                    "adapter": adapter.source_name,
                    "endpoint": endpoint,
                },
            )
            jobs = adapter.fetch_jobs(company)
            company_result.jobs_fetched = len(jobs)
            for job in jobs:
                job.date_last_seen = datetime.now(UTC)
                filtered = apply_filter(job, config.filters, company)
                if filtered.match_status != MatchStatus.MATCHED:
                    continue
                company_result.jobs_matched += 1
                if filtered.deduplication_key in existing_keys:
                    company_result.duplicates_skipped += 1
                    continue
                existing_keys.add(filtered.deduplication_key or "")
                new_jobs_to_insert.append(filtered)
                company_result.new_jobs_inserted += 1
        except Exception as exc:
            message = f"{company.name}: {type(exc).__name__}: {exc}"
            company_result.failures.append(message)
            summary.failures.append(message)
            logger.exception(
                "company job fetch failed",
                extra={
                    "company": company.name,
                    "adapter": adapter.source_name,
                    "endpoint": endpoint,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
        finally:
            summary.company_results.append(company_result)

    summary.jobs_fetched = sum(result.jobs_fetched for result in summary.company_results)
    summary.jobs_matched = sum(result.jobs_matched for result in summary.company_results)
    summary.new_jobs_inserted = sum(result.new_jobs_inserted for result in summary.company_results)
    summary.duplicates_skipped = sum(
        result.duplicates_skipped for result in summary.company_results
    )
    summary.execution_duration_seconds = time.monotonic() - started

    if not dry_run and sheet_store is not None:
        sheet_store.append_jobs(new_jobs_to_insert)
        sheet_store.append_run_log(summary)

    logger.info(
        "job monitor run completed",
        extra={
            "companies_checked": summary.companies_checked,
            "jobs_fetched": summary.jobs_fetched,
            "jobs_matched": summary.jobs_matched,
            "new_jobs_inserted": summary.new_jobs_inserted,
            "duplicates_skipped": summary.duplicates_skipped,
            "failures": summary.failures,
            "duration_seconds": round(summary.execution_duration_seconds, 2),
            "dry_run": dry_run,
        },
    )
    return summary


def _select_companies(config: AppConfig, company_key: str | None) -> list[CompanyConfig]:
    companies = config.enabled_companies()
    if not company_key:
        return companies
    normalized = company_key.casefold()
    selected = [
        company
        for company in companies
        if company.key.casefold() == normalized or company.name.casefold() == normalized
    ]
    if not selected:
        raise ValueError(f"no enabled company matched: {company_key}")
    return selected
