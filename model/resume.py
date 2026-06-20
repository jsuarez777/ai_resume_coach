from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, HttpUrl, PositiveInt, constr, field_validator

ProficiencyLevel = constr(pattern=r"^(Beginner|Intermediate|Advanced|Expert)$")
FitLevel = constr(pattern=r"^(Excellent|Good|Partial|Poor|Mismatch)$")
WritingStyle = constr(pattern=r"^(Formal|Casual|Technical|Achievement|Career-changer)$")


class ContactInfo(BaseModel):
    name: str
    email: EmailStr
    phone: constr(min_length=10)
    location: str
    linkedin: Optional[HttpUrl] = None
    portfolio: Optional[HttpUrl] = None


class EducationEntry(BaseModel):
    degree: str
    institution: str
    graduation_date: date
    gpa: Optional[float] = None
    coursework: Optional[List[str]] = None

    @field_validator("gpa")
    def validate_gpa(cls, value: Optional[float]) -> Optional[float]:
        max_gpa = 4.0
        if value is None:
            return value
        if not 0.0 <= value <= max_gpa:
            raise ValueError(f"GPA must be between 0.0 and {max_gpa}")
        return value


class ExperienceEntry(BaseModel):
    company: str
    title: str
    start_date: date
    end_date: Optional[date] = None
    responsibilities: List[str]
    achievements: List[str]

    @field_validator("end_date")
    def validate_dates(cls, value: Optional[date], info) -> Optional[date]:
        start = info.data.get("start_date")
        if value is not None and start is not None and value <= start:
            raise ValueError("end_date must be after start_date")
        return value


class Skill(BaseModel):
    name: str
    proficiency_level: ProficiencyLevel
    years: Optional[PositiveInt] = None


class ResumeMetadata(BaseModel):
    trace_id: str
    generated_at: datetime
    prompt_template: str
    fit_level: FitLevel
    writing_style: WritingStyle


class Resume(BaseModel):
    contact_info: ContactInfo
    education: List[EducationEntry]
    experience: List[ExperienceEntry]
    skills: List[Skill]
    metadata: ResumeMetadata
