"""Triage agent - classifies issues for auto-fix eligibility."""

from typing import Any

from ..claude_runner import ClaudeTimeoutError, extract_json_from_output, run_claude
from ..models import AgentStatus, Classification
from .base import Agent


class TriageAgent(Agent):
    """Analyzes issues and classifies them for auto-fix eligibility."""

    name = "triage"

    def run(self) -> tuple[AgentStatus, dict[str, Any]]:
        """Execute triage analysis."""
        self.info(f"Starting triage for issue #{self.context.issue.number}")

        # Load and save prompt
        prompt = self.load_prompt_template()
        self.prompt_file.write_text(prompt)

        # Run Claude
        self.info(f"Running Claude (timeout: {self.context.config.triage_timeout}s)...")
        try:
            result = run_claude(
                prompt=prompt,
                cwd=self.context.config.project_dir,
                timeout_sec=self.context.config.triage_timeout,
                log_file=self.log_file,
            )
        except ClaudeTimeoutError as e:
            self.error(str(e))
            return AgentStatus.FAILED, {"error": str(e)}

        if not result.success:
            self.error(f"Claude failed: {result.error}")
            return AgentStatus.FAILED, {"error": result.error}

        # Extract JSON output
        self.info("Extracting triage results...")
        data = extract_json_from_output(result.output, "classification")

        if not data:
            self.warning("Could not extract structured result, defaulting to NEEDS_CLARIFICATION")
            data = {
                "classification": Classification.NEEDS_CLARIFICATION.value,
                "confidence": 0.3,
                "clarity_score": 0.3,
                "feasibility_score": 0.3,
                "summary": "Could not parse issue automatically",
                "reasoning": "Triage agent failed to produce structured output",
                "risks": ["Unknown issue structure"],
                "suggested_approach": "Manual review required",
                "questions_if_unclear": ["What is the expected behavior?"],
                "estimated_complexity": "unknown",
            }

        # Parse and validate classification
        classification_str = data.get("classification", "NEEDS_CLARIFICATION")
        try:
            classification = Classification(classification_str)
        except ValueError:
            classification = Classification.NEEDS_CLARIFICATION

        confidence = float(data.get("confidence", 0.5))
        summary = data.get("summary", "No summary")
        complexity = data.get("estimated_complexity", "unknown")

        self.success(f"Classification: {classification.value} (confidence: {confidence})")
        self.info(f"Summary: {summary}")
        self.info(f"Complexity: {complexity}")

        # Determine if we should proceed
        should_proceed = (
            classification in (Classification.FIXABLE_CODE, Classification.FIXABLE_CONFIG)
            and confidence >= self.context.config.min_triage_confidence
        )

        if should_proceed:
            self.success("Issue approved for auto-fix")
            status = AgentStatus.SUCCESS
        else:
            self.info(f"Issue not suitable for auto-fix: {classification.value}")
            status = AgentStatus.SKIPPED

        return status, {
            "classification": classification.value,
            "confidence": confidence,
            "should_proceed": should_proceed,
            "summary": summary,
            "complexity": complexity,
            "full_analysis": data,
        }
