"""Base agent class."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Config
from ..models import AgentState, AgentStatus, Issue


@dataclass
class AgentContext:
    """Context passed to agents."""
    config: Config
    issue: Issue
    run_dir: Path
    previous_states: dict[str, AgentState] = field(default_factory=dict)


class Agent(ABC):
    """Base class for all agents."""

    name: str = "base"

    def __init__(self, context: AgentContext):
        self.context = context
        self.state = AgentState(
            agent=self.name,
            status=AgentStatus.PENDING,
            issue_number=context.issue.number,
        )

    @property
    def log_file(self) -> Path:
        """Path to agent's log file."""
        return self.context.run_dir / f"{self.name}.log"

    @property
    def state_file(self) -> Path:
        """Path to agent's state file."""
        return self.context.run_dir / f"{self.name}.state.json"

    @property
    def prompt_file(self) -> Path:
        """Path to agent's prompt file."""
        return self.context.run_dir / f"{self.name}.prompt.md"

    def log(self, level: str, message: str) -> None:
        """Log a message."""
        prefix = f"[{self.name.upper()}] [{level}]"
        print(f"{prefix} {message}")

    def info(self, message: str) -> None:
        """Log info message."""
        self.log("INFO", message)

    def success(self, message: str) -> None:
        """Log success message."""
        self.log("SUCCESS", message)

    def warning(self, message: str) -> None:
        """Log warning message."""
        self.log("WARNING", message)

    def error(self, message: str) -> None:
        """Log error message."""
        self.log("ERROR", message)

    def save_state(self) -> None:
        """Save agent state to file."""
        self.state.timestamp = datetime.now()
        with open(self.state_file, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2)

    def load_prompt_template(self) -> str:
        """Load and render the prompt template."""
        template_file = self.context.config.prompts_dir / f"{self.name}.md"
        if not template_file.exists():
            raise FileNotFoundError(f"Prompt template not found: {template_file}")

        template = template_file.read_text()

        # Substitute variables
        issue = self.context.issue
        substitutions = {
            "${ISSUE_NUMBER}": str(issue.number),
            "${ISSUE_TITLE}": issue.title,
            "${ISSUE_BODY}": issue.body,
            "${ISSUE_LABELS}": ", ".join(issue.labels),
        }

        for key, value in substitutions.items():
            template = template.replace(key, value)

        return template

    @abstractmethod
    def run(self) -> tuple[AgentStatus, dict[str, Any]]:
        """Execute the agent's task.

        Returns:
            Tuple of (status, result_data)
        """
        pass

    def execute(self) -> AgentState:
        """Execute the agent and handle state management."""
        self.state.status = AgentStatus.RUNNING
        self.save_state()

        try:
            status, data = self.run()
            self.state.status = status
            self.state.data = data
            self.state.confidence = data.get("confidence", 0.0)

            if status == AgentStatus.SUCCESS:
                self.success(f"{self.name.title()} completed successfully")
            elif status == AgentStatus.SKIPPED:
                self.warning(f"{self.name.title()} skipped")
            else:
                self.error(f"{self.name.title()} failed")

        except Exception as e:
            self.state.status = AgentStatus.FAILED
            self.state.error = str(e)
            self.error(f"{self.name.title()} failed with error: {e}")

        self.save_state()
        return self.state
