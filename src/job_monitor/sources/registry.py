from __future__ import annotations

from job_monitor.config import SourceType
from job_monitor.http import HttpClient
from job_monitor.sources.ashby import AshbySource
from job_monitor.sources.base import JobSource, UnsupportedSource
from job_monitor.sources.greenhouse import GreenhouseSource
from job_monitor.sources.lever import LeverSource


def build_source_registry(http_client: HttpClient | None = None) -> dict[SourceType, JobSource]:
    return {
        SourceType.GREENHOUSE: GreenhouseSource(http_client),
        SourceType.LEVER: LeverSource(http_client),
        SourceType.ASHBY: AshbySource(http_client),
        SourceType.WORKDAY: UnsupportedSource(
            "workday",
            "Workday public career sites vary by tenant and often require tenant-specific parsing.",
        ),
        SourceType.SMARTRECRUITERS: UnsupportedSource(
            "smartrecruiters",
            "SmartRecruiters support is intentionally not claimed until a tested parser is added.",
        ),
        SourceType.CUSTOM: UnsupportedSource(
            "custom",
            "Custom adapters should be implemented explicitly for each nonstandard source.",
        ),
    }
