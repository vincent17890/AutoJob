from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from job_monitor.deduplication import generate_deduplication_key


class MatchStatus(StrEnum):
    MATCHED = "matched"
    FILTERED_OUT = "filtered_out"


class JobPosting(BaseModel):
    stable_job_id: str | None = None
    company: str
    title: str
    location: str | None = None
    employment_type: str | None = None
    department: str | None = None
    description: str | None = None
    posting_url: HttpUrl | str | None = None
    application_url: HttpUrl | str | None = None
    source: str
    source_job_id: str | None = None
    date_posted: date | None = None
    date_first_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    date_last_seen: datetime = Field(default_factory=lambda: datetime.now(UTC))
    matched_keywords: list[str] = Field(default_factory=list)
    match_status: MatchStatus = MatchStatus.FILTERED_OUT
    match_reason: str = ""
    deduplication_key: str | None = None

    @field_validator("title", "company", "source")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("field cannot be empty")
        return value

    @model_validator(mode="after")
    def populate_identifiers(self) -> JobPosting:
        if not self.stable_job_id:
            self.stable_job_id = self.source_job_id
        if not self.deduplication_key:
            self.deduplication_key = generate_deduplication_key(
                company=self.company,
                source_job_id=self.source_job_id,
                application_url=str(self.application_url) if self.application_url else None,
                posting_url=str(self.posting_url) if self.posting_url else None,
                title=self.title,
                location=self.location,
            )
        return self


class CompanyRunResult(BaseModel):
    company: str
    adapter: str
    endpoint: str | None = None
    jobs_fetched: int = 0
    jobs_matched: int = 0
    new_jobs_inserted: int = 0
    duplicates_skipped: int = 0
    failures: list[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    run_timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    companies_checked: int = 0
    jobs_fetched: int = 0
    jobs_matched: int = 0
    new_jobs_inserted: int = 0
    duplicates_skipped: int = 0
    failures: list[str] = Field(default_factory=list)
    execution_duration_seconds: float = 0.0
    company_results: list[CompanyRunResult] = Field(default_factory=list)
