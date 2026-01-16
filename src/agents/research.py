"""Research agent - explores codebase to understand the issue."""

from typing import Any

from ..claude_runner import ClaudeTimeoutError, extract_json_from_output, run_claude
from ..models import AgentStatus
from .base import Agent


class ResearchAgent(Agent):
    """Explores codebase to understand the issue and plan the fix."""

    name = "research"

    def run(self) -> tuple[AgentStatus, dict[str, Any]]:
        """Execute research analysis."""
        self.info(f"Starting research for issue #{self.context.issue.number}")

        # Check that triage passed
        triage_state = self.context.previous_states.get("triage")
        if not triage_state or triage_state.status != AgentStatus.SUCCESS:
            self.error("Triage did not complete successfully")
            return AgentStatus.FAILED, {"error": "Triage not completed"}

        # Load and save prompt - include triage context
        prompt = self.load_prompt_template()

        # Add triage summary to prompt
        triage_data = triage_state.data
        triage_context = f"""
## Previous Triage Analysis

**Classification:** {triage_data.get('classification')}
**Summary:** {triage_data.get('summary')}
**Complexity:** {triage_data.get('complexity')}

Full analysis:
```json
{triage_data.get('full_analysis', {})}
```
"""
        prompt = prompt.replace("${TRIAGE_SUMMARY}", triage_context)
        self.prompt_file.write_text(prompt)

        # Run Claude
        self.info(f"Running Claude (timeout: {self.context.config.research_timeout}s)...")
        try:
            result = run_claude(
                prompt=prompt,
                cwd=self.context.config.project_dir,
                timeout_sec=self.context.config.research_timeout,
                log_file=self.log_file,
            )
        except ClaudeTimeoutError as e:
            self.error(str(e))
            return AgentStatus.FAILED, {"error": str(e)}

        if not result.success:
            self.error(f"Claude failed: {result.error}")
            return AgentStatus.FAILED, {"error": result.error}

        # Extract JSON output
        self.info("Extracting research results...")
        data = extract_json_from_output(result.output, "confidence")

        if not data:
            self.warning("Could not extract structured result")
            data = {
                "confidence": 0.3,
                "files_analyzed": [],
                "root_cause": "Could not determine",
                "proposed_fix": "Manual analysis required",
                "affected_areas": [],
                "test_strategy": "Unknown",
            }

        confidence = float(data.get("confidence", 0.5))
        files_analyzed = data.get("files_analyzed", [])

        self.success(f"Research complete (confidence: {confidence})")
        self.info(f"Files analyzed: {len(files_analyzed)}")

        if confidence < self.context.config.min_research_confidence:
            self.warning(f"Confidence too low ({confidence}), but continuing...")

        return AgentStatus.SUCCESS, {
            "confidence": confidence,
            "files_analyzed": files_analyzed,
            "root_cause": data.get("root_cause", ""),
            "proposed_fix": data.get("proposed_fix", ""),
            "affected_areas": data.get("affected_areas", []),
            "test_strategy": data.get("test_strategy", ""),
            "full_analysis": data,
        }
