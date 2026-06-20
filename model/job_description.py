from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, PositiveInt, constr, field_validator

ExperienceLevel = constr(pattern=r"^(Entry|Junior|Mid|Intermediate|Senior|Lead|Principal|Executive|Director|VP)$")


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


class JobDescription(BaseModel):
    company: CompanyInfo
    requirements: JobRequirements
    metadata: JobMetadata
