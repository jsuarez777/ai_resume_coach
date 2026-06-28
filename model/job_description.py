from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, PositiveInt, conlist, constr, field_validator

ExperienceLevel = constr(
    pattern=r"^(Entry|Junior|Mid|Intermediate|Senior|Lead|Principal|Executive|Director|VP)$"
)

# Free-text length bounds (characters).
SummaryText = constr(strip_whitespace=True, min_length=80, max_length=400)
OverviewText = constr(strip_whitespace=True, min_length=150, max_length=1200)
ResponsibilityText = constr(strip_whitespace=True, min_length=10, max_length=250)
ResponsibilityList = conlist(ResponsibilityText, min_length=3, max_length=10)


def validate_experience_duration_years(years: int, max_years: int = 30) -> int:
    if years > max_years:
        raise ValueError(f"experience value cannot exceed {max_years} years")
    return years


class CompanyInfo(BaseModel):
    name: str
    industry: str
    size: str
    location: str


class JobRequirements(BaseModel):
    required_skills: List[str]
    preferred_skills: List[str]
    education: str
    experience_years: PositiveInt
    experience_level: ExperienceLevel

    @field_validator("experience_years")
    def validate_experience_years(cls, value: int) -> int:
        return validate_experience_duration_years(value)


class JobMetadata(BaseModel):
    trace_id: str
    generated_at: datetime
    is_niche_role: bool
    writing_style: Optional[str] = None


class JobDetails(BaseModel):
    """The core of the posting: a paragraph plus a bullet list of responsibilities."""

    overview: OverviewText
    responsibilities: ResponsibilityList


class JobDescription(BaseModel):
    company: CompanyInfo
    summary: SummaryText
    description: JobDetails
    requirements: JobRequirements
    metadata: JobMetadata
