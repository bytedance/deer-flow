"""Venue calibration profiles for reviewer simulation and rebuttal planning."""

from __future__ import annotations

from pydantic import BaseModel, Field


class VenueProfile(BaseModel):
    """Calibration profile for one target venue."""

    venue_name: str
    domain: str
    expected_contribution_types: list[str] = Field(default_factory=list)
    common_rejection_reasons: list[str] = Field(default_factory=list)
    writing_style_expectations: list[str] = Field(default_factory=list)
    experimental_expectations: list[str] = Field(default_factory=list)
    compliance_expectations: list[str] = Field(default_factory=list)


VENUE_PROFILES: dict[str, VenueProfile] = {
    "Nature": VenueProfile(
        venue_name="Nature",
        domain="biomed",
        expected_contribution_types=["conceptual_shift", "mechanistic_insight", "high_impact_finding"],
        common_rejection_reasons=["incremental novelty", "insufficient mechanistic validation", "limited generalization"],
        writing_style_expectations=["concise high-density prose", "strong abstract significance sentence", "clear limitation statement"],
        experimental_expectations=["multiple orthogonal validations", "robust controls", "quantitative uncertainty reporting"],
        compliance_expectations=["ethics disclosure", "data availability statement", "code availability statement"],
    ),
    "Cell": VenueProfile(
        venue_name="Cell",
        domain="biomed",
        expected_contribution_types=["biological_mechanism", "translational_relevance"],
        common_rejection_reasons=["missing mechanistic evidence", "insufficient controls", "unclear biological significance"],
        writing_style_expectations=["clear figure-first narrative", "highlights and impact framing"],
        experimental_expectations=["independent validation cohort", "sensitivity analysis"],
        compliance_expectations=["ethics disclosure", "resource availability", "reproducibility details"],
    ),
    "NeurIPS": VenueProfile(
        venue_name="NeurIPS",
        domain="ai_cs",
        expected_contribution_types=["algorithmic_novelty", "theoretical_or_empirical_rigor"],
        common_rejection_reasons=["weak novelty", "incomplete baseline comparison", "missing ablations"],
        writing_style_expectations=["clear contribution list", "tight related work positioning", "explicit limitations"],
        experimental_expectations=["strong baselines", "ablation study", "statistical significance or confidence intervals"],
        compliance_expectations=["reproducibility checklist", "code/data release plan", "broader impact statement"],
    ),
    "ICML": VenueProfile(
        venue_name="ICML",
        domain="ai_cs",
        expected_contribution_types=["methodological_novelty", "rigorous_empirical_validation"],
        common_rejection_reasons=["insufficient empirical evidence", "unconvincing comparison", "unclear assumptions"],
        writing_style_expectations=["precise theorem/claim scope", "balanced discussion"],
        experimental_expectations=["multi-dataset experiments", "robustness checks", "ablation and failure cases"],
        compliance_expectations=["reproducibility expectations", "artifact readiness"],
    ),
}


def get_venue_profile(venue_name: str) -> VenueProfile:
    """Get a venue profile by name."""
    key = venue_name.strip()
    if key not in VENUE_PROFILES:
        raise ValueError(f"Unsupported venue profile: {venue_name}")
    return VENUE_PROFILES[key]
