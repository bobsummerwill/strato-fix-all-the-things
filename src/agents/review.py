"""Review agent - self-reviews the fix before creating PR."""

import json
from typing import Any

from ..claude_runner import ClaudeTimeoutError
from ..models import AgentStatus
from .base import Agent


class ReviewAgent(Agent):
    """Reviews the fix before creating a pull request."""

    name = "review"

    def run(self) -> tuple[AgentStatus, dict[str, Any]]:
        """Execute the review."""
        self.info(f"Starting review for issue #{self.context.issue.number}")

        # Check that fix passed
        fix_state = self.context.previous_states.get("fix")
        if not fix_state or fix_state.status != AgentStatus.SUCCESS:
            self.error("Fix did not complete successfully")
            return AgentStatus.FAILED, {"error": "Fix not completed"}

        # Load prompt template and add fix context
        prompt = self.load_prompt_template()

        # Add fix summary to prompt
        fix_data = fix_state.data
        fix_context = f"""
## Fix Summary

**Files Changed:** {', '.join(fix_data.get('files_changed', []))}
**Summary:** {fix_data.get('summary')}
**Tests Added:** {', '.join(fix_data.get('tests_added', []))}

Full fix details:
```json
{json.dumps(fix_data.get('full_result', {}), indent=2)}
```
"""
        prompt = prompt.replace("${FIX_SUMMARY}", fix_context)
        self.prompt_file.write_text(prompt)

        # Run Claude
        self.info(f"Running Claude (timeout: {self.context.config.review_timeout}s)...")
        try:
            result, data = self.run_claude_with_json(
                prompt=prompt,
                required_field="verdict",
                timeout_sec=self.context.config.review_timeout,
            )
        except ClaudeTimeoutError as e:
            self.error(str(e))
            return AgentStatus.FAILED, {"error": str(e)}

        if not result.success:
            self.error(f"Claude failed: {result.error}")
            return AgentStatus.FAILED, {"error": result.error}

        # Extract JSON output
        self.info("Extracting review results...")

        if not data:
            self.error("Could not extract structured result")
            return AgentStatus.FAILED, {"error": "Review output missing required JSON"}

        approved = data.get("approved", False)
        verdict = data.get("verdict", "UNKNOWN")
        confidence = float(data.get("confidence", 0.5))
        concerns = data.get("concerns", [])

        self.info(f"Review verdict: {verdict}")
        self.info(f"Approved: {approved}")
        if concerns:
            self.warning(f"Concerns: {', '.join(concerns)}")

        if approved:
            self.success("Review approved the fix")
            return AgentStatus.SUCCESS, {
                "approved": True,
                "confidence": confidence,
                "verdict": verdict,
                "concerns": concerns,
                "suggestions": data.get("suggestions", []),
            }
        else:
            self.warning(f"Review did not approve: {verdict}")
            return AgentStatus.SKIPPED, {
                "approved": False,
                "confidence": confidence,
                "verdict": verdict,
                "concerns": concerns,
                "suggestions": data.get("suggestions", []),
            }
