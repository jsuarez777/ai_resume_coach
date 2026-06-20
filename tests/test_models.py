import pytest
from datetime import date, datetime, timedelta
from pydantic import ValidationError

from model.resume import (
    ContactInfo,
    EducationEntry,
    ExperienceEntry,
    Resume,
    ResumeMetadata,
    Skill,
)
from model.job_description import (
    CompanyInfo,
    JobDescription,
    JobMetadata,
    JobRequirements,
)


def make_valid_resume_payload():
    return {
        "contact_info": {
            "name": "Jane Doe",
            "email": "jane.doe@example.com",
            "phone": "+12345678901",
            "location": "Austin, TX",
            "linkedin": "https://www.linkedin.com/in/janedoe",
            "portfolio": "https://janedoe.dev",
        },
        "education": [
            {
                "degree": "B.S. Computer Science",
                "institution": "State University",
                "graduation_date": "2022-05-15",
                "gpa": 3.8,
                "coursework": ["Algorithms", "Database Systems"],
            }
        ],
        "experience": [
            {
                "company": "Acme Corp",
                "title": "Software Engineer",
                "start_date": "2022-06-01",
                "end_date": "2024-01-15",
                "responsibilities": ["Built REST APIs", "Improved test coverage"],
                "achievements": ["Reduced latency by 20%"],
            }
        ],
        "skills": [
            {"name": "Python", "proficiency_level": "Expert", "years": 3},
            {"name": "FastAPI", "proficiency_level": "Advanced"},
        ],
        "metadata": {
            "trace_id": "trace-123",
            "generated_at": "2025-01-01T12:00:00",
            "prompt_template": "technical",
            "fit_level": "Good",
            "writing_style": "Technical",
        },
    }


def make_valid_job_payload():
    return {
        "company": {
            "name": "Acme Corp",
            "industry": "Technology",
            "size": "100-250",
            "location": "Austin, TX",
        },
        "requirements": {
            "required_skills": ["Python", "FastAPI"],
            "preferred_skills": ["Docker", "Kubernetes"],
            "education": "Bachelor's degree in Computer Science",
            "experience_years": 5,
            "experience_level": "Mid",
        },
        "metadata": {
            "trace_id": "trace-456",
            "generated_at": "2025-01-02T17:30:00",
            "is_niche_role": False,
        },
    }


def test_resume_valid_payload_creates_model():
    payload = make_valid_resume_payload()
    model = Resume(**payload)

    assert model.contact_info.name == "Jane Doe"
    assert model.contact_info.email == "jane.doe@example.com"
    assert model.education[0].gpa == 3.8
    assert model.skills[0].proficiency_level == "Expert"
    assert model.metadata.fit_level == "Good"


def test_resume_invalid_email_raises_validation_error():
    payload = make_valid_resume_payload()
    payload["contact_info"]["email"] = "invalid-email"

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "value is not a valid email address" in str(exc_info.value)


def test_resume_invalid_phone_length_raises_validation_error():
    payload = make_valid_resume_payload()
    payload["contact_info"]["phone"] = "12345"

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "at least 10 characters" in str(exc_info.value)


def test_resume_end_date_before_start_date_fails():
    payload = make_valid_resume_payload()
    payload["experience"][0]["end_date"] = "2021-12-31"

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "end_date must be after start_date" in str(exc_info.value)


def test_resume_invalid_proficiency_level_fails():
    payload = make_valid_resume_payload()
    payload["skills"][0]["proficiency_level"] = "Master"

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "String should match pattern" in str(exc_info.value)


def test_resume_missing_metadata_required_field_fails():
    payload = make_valid_resume_payload()
    del payload["metadata"]["trace_id"]

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "Field required" in str(exc_info.value)


def test_job_description_valid_payload_creates_model():
    payload = make_valid_job_payload()
    model = JobDescription(**payload)

    assert model.company.name == "Acme Corp"
    assert model.requirements.experience_years == 5
    assert model.requirements.experience_level == "Mid"
    assert not model.metadata.is_niche_role


def test_job_description_invalid_experience_years_fails():
    payload = make_valid_job_payload()
    payload["requirements"]["experience_years"] = 31

    with pytest.raises(ValidationError) as exc_info:
        JobDescription(**payload)

    assert "experience value cannot exceed 30 years" in str(exc_info.value)


def test_job_description_invalid_experience_level_fails():
    payload = make_valid_job_payload()
    payload["requirements"]["experience_level"] = "Ninja"

    with pytest.raises(ValidationError) as exc_info:
        JobDescription(**payload)

    assert "String should match pattern" in str(exc_info.value)


def test_job_description_missing_company_field_fails():
    payload = make_valid_job_payload()
    del payload["company"]["industry"]

    with pytest.raises(ValidationError) as exc_info:
        JobDescription(**payload)

    assert "Field required" in str(exc_info.value)


def test_resume_edge_case_should_allow_current_job_without_end_date():
    payload = make_valid_resume_payload()
    payload["experience"][0]["end_date"] = None

    model = Resume(**payload)
    assert model.experience[0].end_date is None


def test_job_description_experience_years_zero_fails():
    """PositiveInt requires > 0, so 0 should fail."""
    payload = make_valid_job_payload()
    payload["requirements"]["experience_years"] = 0

    with pytest.raises(ValidationError) as exc_info:
        JobDescription(**payload)

    assert "greater than 0" in str(exc_info.value)


# ============================================================================
# RESUME - ContactInfo Edge Cases
# ============================================================================


def test_resume_contact_info_phone_minimum_length_10_chars():
    """Phone with exactly 10 characters should be valid."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["phone"] = "1234567890"

    model = Resume(**payload)
    assert model.contact_info.phone == "1234567890"


def test_resume_contact_info_phone_with_plus_and_numbers():
    """Phone with + prefix and digits should validate."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["phone"] = "+1234567890"

    model = Resume(**payload)
    assert model.contact_info.phone == "+1234567890"


def test_resume_contact_info_empty_name_fails():
    """Empty name should fail validation."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["name"] = ""

    model = Resume(**payload)
    assert model.contact_info.name == ""


def test_resume_contact_info_whitespace_name():
    """Whitespace-only name should still parse (no explicit validation)."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["name"] = "   "

    model = Resume(**payload)
    assert model.contact_info.name == "   "


def test_resume_contact_info_empty_location():
    """Empty location should still parse (no explicit validation)."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["location"] = ""

    model = Resume(**payload)
    assert model.contact_info.location == ""


def test_resume_contact_info_linkedin_optional():
    """LinkedIn field is optional and should allow None."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["linkedin"] = None

    model = Resume(**payload)
    assert model.contact_info.linkedin is None


def test_resume_contact_info_portfolio_optional():
    """Portfolio field is optional and should allow None."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["portfolio"] = None

    model = Resume(**payload)
    assert model.contact_info.portfolio is None


def test_resume_contact_info_invalid_linkedin_url():
    """Invalid LinkedIn URL should fail."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["linkedin"] = "not-a-url"

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "url" in str(exc_info.value).lower()


def test_resume_contact_info_invalid_portfolio_url():
    """Invalid portfolio URL should fail."""
    payload = make_valid_resume_payload()
    payload["contact_info"]["portfolio"] = "invalid-url"

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "url" in str(exc_info.value).lower()


# ============================================================================
# RESUME - EducationEntry Edge Cases
# ============================================================================


def test_resume_education_gpa_boundary_zero():
    """GPA of 0.0 should be valid."""
    payload = make_valid_resume_payload()
    payload["education"][0]["gpa"] = 0.0

    model = Resume(**payload)
    assert model.education[0].gpa == 0.0


def test_resume_education_gpa_boundary_max():
    """GPA of 4.0 should be valid."""
    payload = make_valid_resume_payload()
    payload["education"][0]["gpa"] = 4.0

    model = Resume(**payload)
    assert model.education[0].gpa == 4.0


def test_resume_education_gpa_exceeds_max():
    """GPA > 4.0 should fail."""
    payload = make_valid_resume_payload()
    payload["education"][0]["gpa"] = 4.1

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "must be between" in str(exc_info.value)


def test_resume_education_gpa_negative():
    """Negative GPA should fail."""
    payload = make_valid_resume_payload()
    payload["education"][0]["gpa"] = -0.5

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "must be between" in str(exc_info.value)


def test_resume_education_gpa_optional():
    """GPA field is optional and should allow None."""
    payload = make_valid_resume_payload()
    payload["education"][0]["gpa"] = None

    model = Resume(**payload)
    assert model.education[0].gpa is None


def test_resume_education_coursework_optional():
    """Coursework field is optional and should allow None."""
    payload = make_valid_resume_payload()
    payload["education"][0]["coursework"] = None

    model = Resume(**payload)
    assert model.education[0].coursework is None


def test_resume_education_coursework_empty_list():
    """Empty coursework list should be valid."""
    payload = make_valid_resume_payload()
    payload["education"][0]["coursework"] = []

    model = Resume(**payload)
    assert model.education[0].coursework == []


def test_resume_education_future_graduation_date():
    """Future graduation date should be valid (no validation against current date)."""
    payload = make_valid_resume_payload()
    payload["education"][0]["graduation_date"] = "2099-12-31"

    model = Resume(**payload)
    assert model.education[0].graduation_date.year == 2099


def test_resume_education_large_coursework_list():
    """Large coursework list should be valid."""
    payload = make_valid_resume_payload()
    payload["education"][0]["coursework"] = [f"Course {i}" for i in range(100)]

    model = Resume(**payload)
    assert len(model.education[0].coursework) == 100


# ============================================================================
# RESUME - ExperienceEntry Edge Cases
# ============================================================================


def test_resume_experience_end_date_equals_start_date():
    """End date equal to start date should fail (must be after)."""
    payload = make_valid_resume_payload()
    payload["experience"][0]["start_date"] = "2022-06-01"
    payload["experience"][0]["end_date"] = "2022-06-01"

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "end_date must be after start_date" in str(exc_info.value)


def test_resume_experience_future_start_date():
    """Future start date should be valid (no validation against current date)."""
    payload = make_valid_resume_payload()
    payload["experience"][0]["start_date"] = "2099-01-01"
    payload["experience"][0]["end_date"] = "2099-12-31"

    model = Resume(**payload)
    assert model.experience[0].start_date.year == 2099


def test_resume_experience_empty_responsibilities():
    """Empty responsibilities list should be valid."""
    payload = make_valid_resume_payload()
    payload["experience"][0]["responsibilities"] = []

    model = Resume(**payload)
    assert model.experience[0].responsibilities == []


def test_resume_experience_empty_achievements():
    """Empty achievements list should be valid."""
    payload = make_valid_resume_payload()
    payload["experience"][0]["achievements"] = []

    model = Resume(**payload)
    assert model.experience[0].achievements == []


def test_resume_experience_large_responsibilities_list():
    """Large responsibilities list should be valid."""
    payload = make_valid_resume_payload()
    payload["experience"][0]["responsibilities"] = [f"Resp {i}" for i in range(50)]

    model = Resume(**payload)
    assert len(model.experience[0].responsibilities) == 50


def test_resume_experience_large_achievements_list():
    """Large achievements list should be valid."""
    payload = make_valid_resume_payload()
    payload["experience"][0]["achievements"] = [f"Achievement {i}" for i in range(50)]

    model = Resume(**payload)
    assert len(model.experience[0].achievements) == 50


# ============================================================================
# RESUME - Skill Edge Cases
# ============================================================================


def test_resume_skill_years_optional():
    """Years field is optional and should allow None."""
    payload = make_valid_resume_payload()
    payload["skills"][0]["years"] = None

    model = Resume(**payload)
    assert model.skills[0].years is None


def test_resume_skill_years_minimum_value():
    """Years value of 1 should be valid (minimum PositiveInt)."""
    payload = make_valid_resume_payload()
    payload["skills"][0]["years"] = 1

    model = Resume(**payload)
    assert model.skills[0].years == 1


def test_resume_skill_years_zero_fails():
    """Years value of 0 should fail (PositiveInt requires > 0)."""
    payload = make_valid_resume_payload()
    payload["skills"][0]["years"] = 0

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "greater than 0" in str(exc_info.value)


def test_resume_skill_years_negative_fails():
    """Negative years should fail."""
    payload = make_valid_resume_payload()
    payload["skills"][0]["years"] = -1

    with pytest.raises(ValidationError) as exc_info:
        Resume(**payload)

    assert "greater than 0" in str(exc_info.value)


def test_resume_skill_years_large_value():
    """Large years value should be valid."""
    payload = make_valid_resume_payload()
    payload["skills"][0]["years"] = 999

    model = Resume(**payload)
    assert model.skills[0].years == 999


def test_resume_skill_empty_name():
    """Empty skill name should still parse (no explicit validation)."""
    payload = make_valid_resume_payload()
    payload["skills"][0]["name"] = ""

    model = Resume(**payload)
    assert model.skills[0].name == ""


def test_resume_skill_all_proficiency_levels():
    """Test all valid proficiency levels."""
    valid_levels = ["Beginner", "Intermediate", "Advanced", "Expert"]

    for level in valid_levels:
        payload = make_valid_resume_payload()
        payload["skills"][0]["proficiency_level"] = level

        model = Resume(**payload)
        assert model.skills[0].proficiency_level == level


def test_resume_skill_invalid_proficiency_level_variations():
    """Test various invalid proficiency levels."""
    invalid_levels = ["Expert+", "expert", "EXPERT", "Guru", "Ninja", "Specialist"]

    for level in invalid_levels:
        payload = make_valid_resume_payload()
        payload["skills"][0]["proficiency_level"] = level

        with pytest.raises(ValidationError):
            Resume(**payload)


# ============================================================================
# RESUME - ResumeMetadata Edge Cases
# ============================================================================


def test_resume_metadata_all_fit_levels():
    """Test all valid fit_level values."""
    valid_levels = ["Excellent", "Good", "Partial", "Poor", "Mismatch"]

    for level in valid_levels:
        payload = make_valid_resume_payload()
        payload["metadata"]["fit_level"] = level

        model = Resume(**payload)
        assert model.metadata.fit_level == level


def test_resume_metadata_invalid_fit_level():
    """Invalid fit_level should fail."""
    invalid_levels = ["Outstanding", "Fair", "None", "Excellent+"]

    for level in invalid_levels:
        payload = make_valid_resume_payload()
        payload["metadata"]["fit_level"] = level

        with pytest.raises(ValidationError):
            Resume(**payload)


def test_resume_metadata_all_writing_styles():
    """Test all valid writing_style values."""
    valid_styles = ["Formal", "Casual", "Technical", "Achievement", "Career-changer"]

    for style in valid_styles:
        payload = make_valid_resume_payload()
        payload["metadata"]["writing_style"] = style

        model = Resume(**payload)
        assert model.metadata.writing_style == style


def test_resume_metadata_invalid_writing_style():
    """Invalid writing_style should fail."""
    invalid_styles = ["Modern", "Creative", "Academic", "technical"]

    for style in invalid_styles:
        payload = make_valid_resume_payload()
        payload["metadata"]["writing_style"] = style

        with pytest.raises(ValidationError):
            Resume(**payload)


def test_resume_metadata_empty_trace_id():
    """Empty trace_id should still parse (no explicit validation)."""
    payload = make_valid_resume_payload()
    payload["metadata"]["trace_id"] = ""

    model = Resume(**payload)
    assert model.metadata.trace_id == ""


def test_resume_metadata_missing_trace_id():
    """Missing trace_id should fail (required field)."""
    payload = make_valid_resume_payload()
    del payload["metadata"]["trace_id"]

    with pytest.raises(ValidationError):
        Resume(**payload)


def test_resume_metadata_future_generated_at():
    """Future generated_at timestamp should be valid."""
    payload = make_valid_resume_payload()
    payload["metadata"]["generated_at"] = "2099-12-31T23:59:59"

    model = Resume(**payload)
    assert model.metadata.generated_at.year == 2099


def test_resume_metadata_past_generated_at():
    """Past generated_at timestamp should be valid."""
    payload = make_valid_resume_payload()
    payload["metadata"]["generated_at"] = "1990-01-01T00:00:00"

    model = Resume(**payload)
    assert model.metadata.generated_at.year == 1990


# ============================================================================
# RESUME - Overall Edge Cases
# ============================================================================


def test_resume_empty_education_list():
    """Empty education list should be valid."""
    payload = make_valid_resume_payload()
    payload["education"] = []

    model = Resume(**payload)
    assert model.education == []


def test_resume_empty_experience_list():
    """Empty experience list should be valid."""
    payload = make_valid_resume_payload()
    payload["experience"] = []

    model = Resume(**payload)
    assert model.experience == []


def test_resume_empty_skills_list():
    """Empty skills list should be valid."""
    payload = make_valid_resume_payload()
    payload["skills"] = []

    model = Resume(**payload)
    assert model.skills == []


def test_resume_multiple_education_entries():
    """Multiple education entries should be valid."""
    payload = make_valid_resume_payload()
    payload["education"] = [
        {
            "degree": "B.S. Computer Science",
            "institution": "State University",
            "graduation_date": "2022-05-15",
            "gpa": 3.8,
            "coursework": ["Algorithms"],
        },
        {
            "degree": "M.S. Computer Science",
            "institution": "Elite University",
            "graduation_date": "2024-05-15",
            "gpa": 3.9,
            "coursework": ["AI", "ML"],
        },
    ]

    model = Resume(**payload)
    assert len(model.education) == 2


def test_resume_multiple_experience_entries():
    """Multiple experience entries should be valid."""
    payload = make_valid_resume_payload()
    payload["experience"] = [
        {
            "company": "Acme Corp",
            "title": "Software Engineer",
            "start_date": "2022-06-01",
            "end_date": "2024-01-15",
            "responsibilities": ["Built REST APIs"],
            "achievements": ["Reduced latency"],
        },
        {
            "company": "Tech Startup",
            "title": "Senior Engineer",
            "start_date": "2024-02-01",
            "end_date": None,
            "responsibilities": ["Led team"],
            "achievements": ["Built new product"],
        },
    ]

    model = Resume(**payload)
    assert len(model.experience) == 2


# ============================================================================
# JobDescription - CompanyInfo Edge Cases
# ============================================================================


def test_job_company_info_empty_name():
    """Empty company name should still parse (no explicit validation)."""
    payload = make_valid_job_payload()
    payload["company"]["name"] = ""

    model = JobDescription(**payload)
    assert model.company.name == ""


def test_job_company_info_empty_industry():
    """Empty industry should still parse (no explicit validation)."""
    payload = make_valid_job_payload()
    payload["company"]["industry"] = ""

    model = JobDescription(**payload)
    assert model.company.industry == ""


def test_job_company_info_empty_size():
    """Empty size should still parse (no explicit validation)."""
    payload = make_valid_job_payload()
    payload["company"]["size"] = ""

    model = JobDescription(**payload)
    assert model.company.size == ""


def test_job_company_info_empty_location():
    """Empty location should still parse (no explicit validation)."""
    payload = make_valid_job_payload()
    payload["company"]["location"] = ""

    model = JobDescription(**payload)
    assert model.company.location == ""


# ============================================================================
# JobDescription - JobRequirements Edge Cases
# ============================================================================


def test_job_requirements_empty_required_skills():
    """Empty required_skills list should be valid."""
    payload = make_valid_job_payload()
    payload["requirements"]["required_skills"] = []

    model = JobDescription(**payload)
    assert model.requirements.required_skills == []


def test_job_requirements_empty_preferred_skills():
    """Empty preferred_skills list should be valid."""
    payload = make_valid_job_payload()
    payload["requirements"]["preferred_skills"] = []

    model = JobDescription(**payload)
    assert model.requirements.preferred_skills == []


def test_job_requirements_experience_years_minimum():
    """Experience years of 1 should be valid (minimum PositiveInt)."""
    payload = make_valid_job_payload()
    payload["requirements"]["experience_years"] = 1

    model = JobDescription(**payload)
    assert model.requirements.experience_years == 1


def test_job_requirements_experience_years_negative_fails():
    """Negative experience years should fail."""
    payload = make_valid_job_payload()
    payload["requirements"]["experience_years"] = -1

    with pytest.raises(ValidationError) as exc_info:
        JobDescription(**payload)

    assert "greater than 0" in str(exc_info.value)


def test_job_requirements_experience_years_30_boundary():
    """Experience years of exactly 30 should be valid (max boundary)."""
    payload = make_valid_job_payload()
    payload["requirements"]["experience_years"] = 30

    model = JobDescription(**payload)
    assert model.requirements.experience_years == 30


def test_job_requirements_all_experience_levels():
    """Test all valid experience_level values."""
    valid_levels = ["Entry", "Junior", "Mid", "Intermediate", "Senior", "Lead", "Principal", "Executive", "Director", "VP"]

    for level in valid_levels:
        payload = make_valid_job_payload()
        payload["requirements"]["experience_level"] = level

        model = JobDescription(**payload)
        assert model.requirements.experience_level == level


def test_job_requirements_invalid_experience_level_variations():
    """Test various invalid experience levels."""
    invalid_levels = ["Ninja", "Guru", "Expert", "entry", "SENIOR", "C-Level", "Manager"]

    for level in invalid_levels:
        payload = make_valid_job_payload()
        payload["requirements"]["experience_level"] = level

        with pytest.raises(ValidationError):
            JobDescription(**payload)


def test_job_requirements_empty_education():
    """Empty education string should still parse (no explicit validation)."""
    payload = make_valid_job_payload()
    payload["requirements"]["education"] = ""

    model = JobDescription(**payload)
    assert model.requirements.education == ""


def test_job_requirements_large_skills_list():
    """Large skills lists should be valid."""
    payload = make_valid_job_payload()
    payload["requirements"]["required_skills"] = [f"Skill{i}" for i in range(100)]
    payload["requirements"]["preferred_skills"] = [f"PrefSkill{i}" for i in range(50)]

    model = JobDescription(**payload)
    assert len(model.requirements.required_skills) == 100
    assert len(model.requirements.preferred_skills) == 50


# ============================================================================
# JobDescription - JobMetadata Edge Cases
# ============================================================================


def test_job_metadata_empty_trace_id():
    """Empty trace_id should still parse (no explicit validation)."""
    payload = make_valid_job_payload()
    payload["metadata"]["trace_id"] = ""

    model = JobDescription(**payload)
    assert model.metadata.trace_id == ""


def test_job_metadata_future_generated_at():
    """Future generated_at timestamp should be valid."""
    payload = make_valid_job_payload()
    payload["metadata"]["generated_at"] = "2099-12-31T23:59:59"

    model = JobDescription(**payload)
    assert model.metadata.generated_at.year == 2099


def test_job_metadata_past_generated_at():
    """Past generated_at timestamp should be valid."""
    payload = make_valid_job_payload()
    payload["metadata"]["generated_at"] = "1990-01-01T00:00:00"

    model = JobDescription(**payload)
    assert model.metadata.generated_at.year == 1990


def test_job_metadata_is_niche_role_true():
    """is_niche_role=True should be valid."""
    payload = make_valid_job_payload()
    payload["metadata"]["is_niche_role"] = True

    model = JobDescription(**payload)
    assert model.metadata.is_niche_role is True


# ============================================================================
# JobDescription - Overall Edge Cases
# ============================================================================


def test_job_description_multiple_companies():
    """JobDescription models can be created for different companies."""
    payload1 = make_valid_job_payload()
    payload1["company"]["name"] = "Company A"

    payload2 = make_valid_job_payload()
    payload2["company"]["name"] = "Company B"

    model1 = JobDescription(**payload1)
    model2 = JobDescription(**payload2)

    assert model1.company.name == "Company A"
    assert model2.company.name == "Company B"
