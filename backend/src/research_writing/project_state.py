"""Project-state models for long-horizon academic writing workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

MilestoneStatus = Literal["pending", "in_progress", "completed", "blocked"]
SectionStatus = Literal["outlined", "drafting", "reviewed", "finalized"]


class ResearchMilestone(BaseModel):
    """Milestone in a research-writing project."""

    milestone_id: str
    title: str
    status: MilestoneStatus = "pending"
    due_date: str | None = None
    notes: str | None = None


class SectionDraft(BaseModel):
    """Section-level draft with dependency references."""

    section_id: str
    section_name: str
    status: SectionStatus = "outlined"
    version: int = 1
    content: str = ""
    claim_ids: list[str] = Field(default_factory=list)
    fact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    citation_ids: list[str] = Field(default_factory=list)


class ReviewerComment(BaseModel):
    """Structured reviewer comment item."""

    comment_id: str
    reviewer_label: str
    severity: Literal["major", "minor", "question"] = "minor"
    content: str
    section_ref: str | None = None


class RebuttalAction(BaseModel):
    """Structured rebuttal action item linked to a reviewer comment."""

    comment_id: str
    action: Literal["manuscript_revision", "new_analysis", "new_experiment", "clarification", "decline_with_rationale"]
    status: Literal["planned", "in_progress", "completed"] = "planned"
    evidence_ids: list[str] = Field(default_factory=list)
    section_ids: list[str] = Field(default_factory=list)
    rebuttal_text: str = ""


class HitlDecision(BaseModel):
    """Human-in-the-loop action decision persisted in project metadata."""

    action_id: str
    source: str = ""
    label: str = ""
    decision: Literal["pending", "approved", "rejected"] = "pending"
    section_id: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchProject(BaseModel):
    """Top-level research project state."""

    project_id: str
    title: str
    discipline: str
    target_venue: str | None = None
    research_questions: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    milestones: list[ResearchMilestone] = Field(default_factory=list)
    sections: list[SectionDraft] = Field(default_factory=list)
    reviewer_comments: list[ReviewerComment] = Field(default_factory=list)
    rebuttal_actions: list[RebuttalAction] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class _ProjectStatePayload(BaseModel):
    """Serialized payload for all projects in a workspace."""

    projects: dict[str, ResearchProject] = Field(default_factory=dict)


class ResearchProjectStateStore:
    """File-backed store for research project state."""

    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_payload(self) -> _ProjectStatePayload:
        if not self.storage_path.exists():
            return _ProjectStatePayload()
        data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _ProjectStatePayload()
        return _ProjectStatePayload.model_validate(data)

    def _save_payload(self, payload: _ProjectStatePayload) -> None:
        self.storage_path.write_text(payload.model_dump_json(indent=2), encoding="utf-8")

    def upsert_project(self, project: ResearchProject) -> ResearchProject:
        payload = self._load_payload()
        payload.projects[project.project_id] = project
        self._save_payload(payload)
        return project

    def get_project(self, project_id: str) -> ResearchProject | None:
        payload = self._load_payload()
        return payload.projects.get(project_id)

    def list_projects(self) -> list[ResearchProject]:
        payload = self._load_payload()
        return list(payload.projects.values())

    def upsert_section(self, project_id: str, section: SectionDraft) -> SectionDraft:
        payload = self._load_payload()
        project = payload.projects.get(project_id)
        if project is None:
            raise ValueError(f"Project '{project_id}' not found")
        remaining = [s for s in project.sections if s.section_id != section.section_id]
        project.sections = [*remaining, section]
        payload.projects[project_id] = project
        self._save_payload(payload)
        return section
