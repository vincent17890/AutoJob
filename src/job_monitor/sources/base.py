from __future__ import annotations

from typing import Protocol

from job_monitor.config import CompanyConfig
from job_monitor.models import JobPosting


class JobSource(Protocol):
    source_name: str

    def endpoint_for(self, company: CompanyConfig) -> str: ...

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]: ...


class UnsupportedSource:
    def __init__(self, source_name: str, reason: str) -> None:
        self.source_name = source_name
        self.reason = reason

    def endpoint_for(self, company: CompanyConfig) -> str:
        return str(company.api_endpoint or company.careers_url or company.ats_identifier or "")

    def fetch_jobs(self, company: CompanyConfig) -> list[JobPosting]:
        raise NotImplementedError(f"{self.source_name} is not supported in this MVP: {self.reason}")
