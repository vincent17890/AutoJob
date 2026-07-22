from __future__ import annotations

from job_monitor.config import SourceType
from job_monitor.http import HttpClient
from job_monitor.sources.ashby import AshbySource
from job_monitor.sources.avature import AvatureSource
from job_monitor.sources.base import JobSource, UnsupportedSource
from job_monitor.sources.eightfold import EightfoldSource
from job_monitor.sources.greenhouse import GreenhouseSource
from job_monitor.sources.icims import ICIMSSource
from job_monitor.sources.lever import LeverSource
from job_monitor.sources.smartrecruiters import SmartRecruitersSource
from job_monitor.sources.successfactors import SuccessFactorsSource
from job_monitor.sources.workday import WorkdaySource


def build_source_registry(http_client: HttpClient | None = None) -> dict[SourceType, JobSource]:
    return {
        SourceType.GREENHOUSE: GreenhouseSource(http_client),
        SourceType.LEVER: LeverSource(http_client),
        SourceType.ASHBY: AshbySource(http_client),
        SourceType.WORKDAY: WorkdaySource(),
        SourceType.SMARTRECRUITERS: SmartRecruitersSource(http_client),
        SourceType.EIGHTFOLD: EightfoldSource(http_client),
        SourceType.ICIMS: ICIMSSource(http_client),
        SourceType.AVATURE: AvatureSource(http_client),
        SourceType.SUCCESSFACTORS: SuccessFactorsSource(http_client),
        SourceType.CUSTOM: UnsupportedSource(
            "custom",
            "Custom adapters should be implemented explicitly for each nonstandard source.",
        ),
    }
