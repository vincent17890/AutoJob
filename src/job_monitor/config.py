from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator, model_validator


class SourceType(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    WORKDAY = "workday"
    SMARTRECRUITERS = "smartrecruiters"
    CUSTOM = "custom"


DEFAULT_TITLE_KEYWORDS = [
    "data scientist",
    "applied scientist",
    "research scientist",
    "machine learning",
    "ml engineer",
    "ai engineer",
    "ai research",
    "software engineer",
    "llm",
    "large language model",
    "generative ai",
    "agent",
    "retrieval",
    "ranking",
    "recommendation",
    "experimentation",
    "causal inference",
    "forecasting",
]

DEFAULT_DESCRIPTION_KEYWORDS = [
    "machine learning",
    "artificial intelligence",
    "generative ai",
    "large language models",
    "llm",
    "agents",
    "model evaluation",
    "retrieval",
    "recommendation systems",
    "experimentation",
    "causal inference",
    "forecasting",
    "ml infrastructure",
]

DEFAULT_EXCLUDED_KEYWORDS = [
    "intern",
    "internship",
    "sales",
    "recruiter",
    "recruiting",
    "nursing",
    "warehouse",
    "technician",
    "customer support",
    "marketing",
]

DEFAULT_LOCATION_KEYWORDS = [
    "united states",
    "usa",
    "us",
    "remote",
    "hybrid",
    "california",
    "new york",
    "washington",
    "texas",
    "massachusetts",
]


class FilterConfig(BaseModel):
    title_keywords: list[str] = Field(default_factory=lambda: DEFAULT_TITLE_KEYWORDS.copy())
    description_keywords: list[str] = Field(
        default_factory=lambda: DEFAULT_DESCRIPTION_KEYWORDS.copy()
    )
    exclude_keywords: list[str] = Field(default_factory=lambda: DEFAULT_EXCLUDED_KEYWORDS.copy())
    locations: list[str] = Field(default_factory=lambda: DEFAULT_LOCATION_KEYWORDS.copy())
    remote_allowed: bool = True
    employment_types: list[str] = Field(default_factory=list)
    seniority_exclude: list[str] = Field(
        default_factory=lambda: ["director", "vp", "vice president", "executive"]
    )
    allow_internships: bool = False

    @field_validator(
        "title_keywords",
        "description_keywords",
        "exclude_keywords",
        "locations",
        "employment_types",
        "seniority_exclude",
    )
    @classmethod
    def strip_values(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value and value.strip()]


class CompanyConfig(BaseModel):
    name: str
    slug: str | None = None
    enabled: bool = True
    source_type: SourceType
    careers_url: HttpUrl | None = None
    api_endpoint: HttpUrl | None = None
    ats_identifier: str | None = None
    location_filters: list[str] = Field(default_factory=list)
    title_keywords_include: list[str] = Field(default_factory=list)
    title_keywords_exclude: list[str] = Field(default_factory=list)
    description_keywords_include: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def name_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("company name is required")
        return value

    @field_validator(
        "location_filters",
        "title_keywords_include",
        "title_keywords_exclude",
        "description_keywords_include",
        "employment_types",
    )
    @classmethod
    def strip_list_values(cls, values: list[str]) -> list[str]:
        return [value.strip() for value in values if value and value.strip()]

    @model_validator(mode="after")
    def require_source_locator(self) -> CompanyConfig:
        supported_source_without_locator = (
            self.source_type in {SourceType.GREENHOUSE, SourceType.LEVER, SourceType.ASHBY}
            and not self.api_endpoint
            and not self.ats_identifier
        )
        if supported_source_without_locator:
            raise ValueError(f"{self.source_type} companies require api_endpoint or ats_identifier")
        return self

    @property
    def key(self) -> str:
        return self.slug or self.name.lower().replace(" ", "-")


class AppConfig(BaseModel):
    filters: FilterConfig = Field(default_factory=FilterConfig)
    companies: list[CompanyConfig]

    @model_validator(mode="after")
    def require_companies(self) -> AppConfig:
        if not self.companies:
            raise ValueError("at least one company must be configured")
        return self

    def enabled_companies(self) -> list[CompanyConfig]:
        return [company for company in self.companies if company.enabled]


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"configuration file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"invalid configuration in {config_path}: {exc}") from exc
