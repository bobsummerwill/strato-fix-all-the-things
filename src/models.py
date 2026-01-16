"""Data models for the pipeline."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Classification(str, Enum):
    """Issue classification types."""
    FIXABLE_CODE = "FIXABLE_CODE"
    FIXABLE_CONFIG = "FIXABLE_CONFIG"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    DUPLICATE = "DUPLICATE"


class AgentStatus(str, Enum):
    """Agent execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineStatus(str, Enum):
    """Overall pipeline status."""
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


@dataclass
class Issue:
    """GitHub issue data."""
    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class AgentState:
    """State of an agent execution."""
    agent: str
    status: AgentStatus
    issue_number: int
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 0.0
    error: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent": self.agent,
            "status": self.status.value,
            "issue_number": self.issue_number,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence,
            "error": self.error,
            **self.data,
        }


@dataclass
class TriageResult:
    """Result from triage agent."""
    classification: Classification
    confidence: float
    clarity_score: float
    feasibility_score: float
    summary: str
    reasoning: str
    risks: list[str]
    suggested_approach: str
    questions_if_unclear: list[str]
    estimated_complexity: str

    @property
    def should_proceed(self) -> bool:
        """Whether the pipeline should proceed with auto-fix."""
        return (
            self.classification in (Classification.FIXABLE_CODE, Classification.FIXABLE_CONFIG)
            and self.confidence >= 0.6
        )


@dataclass
class ResearchResult:
    """Result from research agent."""
    confidence: float
    files_analyzed: list[str]
    root_cause: str
    proposed_fix: str
    affected_areas: list[str]
    test_strategy: str


@dataclass
class FixResult:
    """Result from fix agent."""
    confidence: float
    files_changed: list[str]
    summary: str
    tests_added: list[str]


@dataclass
class ReviewResult:
    """Result from review agent."""
    approved: bool
    confidence: float
    verdict: str
    concerns: list[str]
    suggestions: list[str]


@dataclass
class PipelineState:
    """Overall pipeline state."""
    status: PipelineStatus
    issue_number: int
    current_agent: str = ""
    agents_completed: list[str] = field(default_factory=list)
    failure_reason: str = ""
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    aggregate_confidence: float = 0.0
    confidence_breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "issue_number": self.issue_number,
            "current_agent": self.current_agent,
            "agents_completed": self.agents_completed,
            "failure_reason": self.failure_reason,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": (
                (self.completed_at or datetime.now()) - self.started_at
            ).total_seconds(),
            "aggregate_confidence": self.aggregate_confidence,
            "confidence_breakdown": self.confidence_breakdown,
        }
