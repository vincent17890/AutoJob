from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Any, Protocol

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from job_monitor.models import JobPosting, RunSummary

logger = logging.getLogger(__name__)

JOBS_SHEET = "Jobs"
RUN_LOG_SHEET = "Run Log"

JOB_HEADERS = [
    "Company",
    "Title",
    "Location",
    "Department",
    "Employment Type",
    "Date Posted",
    "First Seen",
    "Match Reason",
    "Posting URL",
    "Application URL",
    "Source",
    "Source Job ID",
    "Deduplication Key",
    "Status",
    "Notes",
]

RUN_LOG_HEADERS = [
    "Run Timestamp",
    "Companies Checked",
    "Jobs Fetched",
    "Jobs Matched",
    "New Jobs Inserted",
    "Duplicates Skipped",
    "Failures",
    "Execution Duration Seconds",
]


class SheetStore(Protocol):
    def existing_deduplication_keys(self) -> set[str]: ...

    def append_jobs(self, jobs: list[JobPosting]) -> None: ...

    def append_run_log(self, summary: RunSummary) -> None: ...


class GoogleSheetStore:
    def __init__(self, spreadsheet_id: str, service: Any) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._service = service

    @classmethod
    def from_environment(cls) -> GoogleSheetStore:
        spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID")
        raw_credentials = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not spreadsheet_id:
            raise RuntimeError("GOOGLE_SHEET_ID is required")
        if not raw_credentials:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is required")

        credentials_info = json.loads(raw_credentials)
        client_email = credentials_info.get("client_email", "unknown")
        logger.info(
            "creating google sheets client",
            extra={"service_account_email": client_email},
        )
        credentials = Credentials.from_service_account_info(
            credentials_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return cls(spreadsheet_id, service)

    def ensure_worksheets(self) -> None:
        metadata = self._service.spreadsheets().get(spreadsheetId=self._spreadsheet_id).execute()
        spreadsheet_title = metadata.get("properties", {}).get("title", "unknown")
        existing_titles = {
            sheet["properties"]["title"]
            for sheet in metadata.get("sheets", [])
            if "properties" in sheet
        }
        logger.info(
            "loaded spreadsheet metadata",
            extra={
                "spreadsheet_title": spreadsheet_title,
                "worksheet_titles": sorted(existing_titles),
            },
        )
        requests = []
        for title in [JOBS_SHEET, RUN_LOG_SHEET]:
            if title not in existing_titles:
                requests.append({"addSheet": {"properties": {"title": title}}})
        if requests:
            logger.info(
                "creating missing worksheets",
                extra={
                    "worksheet_titles": [
                        request["addSheet"]["properties"]["title"] for request in requests
                    ]
                },
            )
            self._service.spreadsheets().batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ).execute()

        self._ensure_header(JOBS_SHEET, JOB_HEADERS)
        self._ensure_header(RUN_LOG_SHEET, RUN_LOG_HEADERS)

    def existing_deduplication_keys(self) -> set[str]:
        self.ensure_worksheets()
        values = self._values_get(f"{JOBS_SHEET}!A:O")
        if not values:
            return set()
        header = values[0]
        try:
            key_index = header.index("Deduplication Key")
        except ValueError:
            return set()
        return {row[key_index] for row in values[1:] if len(row) > key_index and row[key_index]}

    def append_jobs(self, jobs: list[JobPosting]) -> None:
        if not jobs:
            logger.info("no matched jobs to append")
            return
        self.ensure_worksheets()
        logger.info("appending matched jobs", extra={"rows": len(jobs), "worksheet": JOBS_SHEET})
        self._values_append(
            f"{JOBS_SHEET}!A:O",
            [job_to_row(job) for job in jobs],
        )

    def append_run_log(self, summary: RunSummary) -> None:
        self.ensure_worksheets()
        logger.info("appending run log", extra={"worksheet": RUN_LOG_SHEET})
        self._values_append(
            f"{RUN_LOG_SHEET}!A:H",
            [
                [
                    summary.run_timestamp.isoformat(),
                    summary.companies_checked,
                    summary.jobs_fetched,
                    summary.jobs_matched,
                    summary.new_jobs_inserted,
                    summary.duplicates_skipped,
                    "\n".join(summary.failures),
                    round(summary.execution_duration_seconds, 2),
                ]
            ],
        )

    def _ensure_header(self, sheet_name: str, headers: list[str]) -> None:
        values = self._values_get(f"{sheet_name}!A1:{chr(ord('A') + len(headers) - 1)}1")
        if not values:
            logger.info("writing worksheet header", extra={"worksheet": sheet_name})
            self._service.spreadsheets().values().update(
                spreadsheetId=self._spreadsheet_id,
                range=f"{sheet_name}!A1",
                valueInputOption="RAW",
                body={"values": [headers]},
            ).execute()

    def _values_get(self, range_name: str) -> list[list[str]]:
        result = (
            self._service.spreadsheets()
            .values()
            .get(spreadsheetId=self._spreadsheet_id, range=range_name)
            .execute()
        )
        return result.get("values", [])

    def _values_append(self, range_name: str, rows: list[list[Any]]) -> None:
        self._service.spreadsheets().values().append(
            spreadsheetId=self._spreadsheet_id,
            range=range_name,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()


class InMemorySheetStore:
    def __init__(self, existing_keys: set[str] | None = None) -> None:
        self.jobs: list[JobPosting] = []
        self.run_logs: list[RunSummary] = []
        self._existing_keys = existing_keys or set()

    def existing_deduplication_keys(self) -> set[str]:
        return self._existing_keys | {
            job.deduplication_key for job in self.jobs if job.deduplication_key
        }

    def append_jobs(self, jobs: list[JobPosting]) -> None:
        self.jobs.extend(jobs)

    def append_run_log(self, summary: RunSummary) -> None:
        self.run_logs.append(summary)


def job_to_row(job: JobPosting) -> list[str]:
    return [
        job.company,
        job.title,
        job.location or "",
        job.department or "",
        job.employment_type or "",
        _format_date(job.date_posted),
        job.date_first_seen.isoformat(),
        job.match_reason,
        str(job.posting_url or ""),
        str(job.application_url or ""),
        job.source,
        job.source_job_id or "",
        job.deduplication_key or "",
        job.match_status.value,
        "",
    ]


def _format_date(value: date | None) -> str:
    return value.isoformat() if value else ""
