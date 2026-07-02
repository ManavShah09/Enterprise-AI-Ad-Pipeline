"""
Stage 1 Agent — Transcript Structuring.

Creates an Azure AI Foundry agent that takes a raw advertisement transcript
and structures it into: Intro, numbered Content Blocks, and a CTA.

The agent is instructed to return ONLY valid JSON matching the Stage1Output schema.
"""

import json
import logging

# pyrefly: ignore [missing-import]
from azure.ai.projects.models import PromptAgentDefinition

from src.client_setup import project_client, openai_client, MODEL_DEPLOYMENT_NAME
from src.schemas import Stage1Output

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "stage1-transcript-structuring"

# The JSON schema is embedded in the instructions so the agent knows the
# exact structure to produce.
_SCHEMA_EXAMPLE = json.dumps(Stage1Output.model_json_schema(), indent=2)

SYSTEM_INSTRUCTIONS = f"""You are a Transcript Structuring Specialist.

## Your Task
Given a raw advertisement transcript, break it down into exactly three parts:
1. **intro** — The opening hook or introduction of the advertisement.
2. **content_blocks** — An ordered list of the main content sections. Each block must include:
   - `block_number`: Sequential integer starting from 1.
   - `text`: The full text of that content section.3. **cta** — The closing Call-to-Action.

## Rules
- Preserve the original wording from the transcript. Do NOT paraphrase or rewrite.
- Identify natural transitions to determine where one block ends and the next begins.
- The intro should capture everything before the first main content section.
- The CTA should capture the final call-to-action or closing statement.
- If no clear CTA exists, use the last sentence or paragraph.
- Every transcript must produce at least one content block.

## Output Format
Respond ONLY with valid JSON. No markdown code fences, no explanation, no extra text.

The JSON must conform to this exact schema:
{_SCHEMA_EXAMPLE}

## Example Output
{{
  "intro": "Are you tired of spending hours on manual outreach?",
  "content_blocks": [
    {{
      "block_number": 1,
      "text": "Relay Human Cloud connects you with vetted professionals...",
      "summary": "Introduces Relay's core service."
    }},
    {{
      "block_number": 2,
      "text": "Our clients see a 3x improvement in response rates...",
      "summary": "Presents social proof with metrics."
    }}
  ],
  "cta": "Book a free discovery call today at relay.app/demo"
}}
"""


# ---------------------------------------------------------------------------
# Agent creation & execution
# ---------------------------------------------------------------------------

def _create_or_update_agent():
    """Create (or update) the Stage 1 agent in Azure AI Foundry."""
    logger.info("Creating/updating Stage 1 agent: %s", AGENT_NAME)

    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=SYSTEM_INSTRUCTIONS,
        ),
    )
    logger.info("Agent ready: name=%s, version=%s", agent.name, agent.version)
    return agent


def run_stage1(transcript: str) -> tuple[str, dict]:
    """
    Run the Stage 1 agent on the given transcript.

    Args:
        transcript: The raw advertisement transcript text.

    Returns:
        A tuple of (raw_output_text, usage_dict).
        usage_dict contains input_tokens, output_tokens, total_tokens.

    Raises:
        RuntimeError: If the agent returns an empty response.
    """
    # Ensure the agent exists
    agent = _create_or_update_agent()

    logger.info("Running Stage 1 agent on transcript (%d chars)...", len(transcript))

    # Generate a response using the agent
    response = openai_client.responses.create(
        extra_body={
            "agent_reference": {
                "name": agent.name,
                "type": "agent_reference",
            }
        },
        input=transcript,
    )

    raw_output = response.output_text
    if not raw_output or not raw_output.strip():
        raise RuntimeError("Stage 1 agent returned an empty response.")

    # Extract token usage
    usage = _extract_usage(response)
    logger.info(
        "Stage 1 agent returned %d chars | Tokens: in=%d, out=%d, total=%d",
        len(raw_output), usage["input_tokens"], usage["output_tokens"], usage["total_tokens"],
    )
    return raw_output.strip(), usage


def _extract_usage(response) -> dict:
    """Extract token usage from the OpenAI response object."""
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    try:
        if hasattr(response, "usage") and response.usage is not None:
            usage["input_tokens"] = getattr(response.usage, "input_tokens", 0) or 0
            usage["output_tokens"] = getattr(response.usage, "output_tokens", 0) or 0
            usage["total_tokens"] = getattr(response.usage, "total_tokens", 0) or 0
            # If total not provided, compute it
            if usage["total_tokens"] == 0:
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    except Exception as e:
        logger.warning("Could not extract token usage: %s", e)
    return usage

