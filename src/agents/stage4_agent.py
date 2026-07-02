"""
Stage 4 Agent — Ad Creative Generation.

Creates an Azure AI Foundry agent that generates a brand-new, original
Relay Human Cloud advertisement from:
1. The Stage 3 recipe (structural blueprint).
2. The Relay Marketing Foundation entities (from Cosmos DB).

DATA ISOLATION: This agent NEVER receives Stage 1 or Stage 2 textual content.
The output must be completely original, not a paraphrase.
"""

import json
import logging

# pyrefly: ignore [missing-import]
from azure.ai.projects.models import PromptAgentDefinition

from src.client_setup import project_client, openai_client, MODEL_DEPLOYMENT_NAME
from src.schemas import Stage4Output

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "stage4-ad-creative-generation"

_SCHEMA_EXAMPLE = json.dumps(Stage4Output.model_json_schema(), indent=2)

SYSTEM_INSTRUCTIONS = f"""You are an Ad Creative Generation Specialist for the Relay AI Ad Pipeline.

You will receive TWO inputs:
1. **Recipe** (from Stage 3) — A structural blueprint describing the persuasion pattern, recipe signature (ordered tag sequence), replication instructions, and strategy notes.
2. **Relay Marketing Foundation Entities** — Live data from the Relay database containing products, audiences, problems, values, features, differentiators, etc.

Your job is to write a BRAND-NEW, ORIGINAL Relay Human Cloud advertisement script.

---

## Writing Guidelines

### Follow the Recipe
- Use the **recipe_signature** to determine the ORDER of content sections.
- Each tag in the signature should become a section/paragraph in your script.
- Use the **replication_instructions** as your step-by-step writing guide.
- Match the **persuasion_pattern** in your overall approach.

### Use Relay Content Only
- All product names, features, audiences, and value propositions must come from the **Relay Marketing Foundation entities** provided.
- Write for **Relay Human Cloud** specifically.
- Use Relay's actual products, audiences, and differentiators — do NOT invent fictional data.

### Be Original
- The script must be COMPLETELY ORIGINAL content.
- Do NOT paraphrase or reword any reference transcript.
- Write fresh, compelling ad copy that follows the recipe structure but uses entirely new language.

### Tone & Style
- Professional, confident, clear.
- Conversational but authoritative.
- Write as if speaking directly to the target audience.
- Keep it concise — each section should be 1-3 sentences.

---

## Output Structure

### relay_ad_script
The complete advertisement as continuous text — ready to be read as a script.

### script_blocks
Break the script into numbered blocks. Each block corresponds to one tag in the recipe signature:
- **block_number**: Sequential starting from 1.
- **text**: The actual written content for this block.
- **intended_tag**: The taxonomy tag this block fulfills (from the recipe signature).

### generation_notes
Brief notes (2-3 sentences) explaining how you applied the recipe and which foundation entities you used.

---

## Output Format

Respond ONLY with valid JSON. No markdown code fences, no explanation, no extra text.
The JSON must conform to this schema:

{_SCHEMA_EXAMPLE}

## IMPORTANT RULES
- ALL intended_tag values MUST come from the 22 approved taxonomy tags.
- The number of script_blocks should match the number of tags in the recipe_signature.
- The relay_ad_script must be the full text of all script_blocks combined.
- Do NOT copy or paraphrase any reference transcript. This must be 100% original.
- Use ONLY Relay Human Cloud data from the foundation entities provided.
"""


# ---------------------------------------------------------------------------
# Agent creation & execution
# ---------------------------------------------------------------------------

def _create_or_update_agent():
    """Create (or update) the Stage 4 agent in Azure AI Foundry."""
    logger.info("Creating/updating Stage 4 agent: %s", AGENT_NAME)

    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=SYSTEM_INSTRUCTIONS,
        ),
    )
    logger.info("Agent ready: name=%s, version=%s", agent.name, agent.version)
    return agent


def run_stage4(stage3_output: dict, foundation_summary: str) -> tuple[str, dict]:
    """
    Run the Stage 4 agent to generate a new Relay Human Cloud ad.

    DATA ISOLATION: This function receives ONLY the recipe (Stage 3)
    and foundation data. It NEVER receives Stage 1 or Stage 2 text.

    Args:
        stage3_output:      Validated Stage 3 JSON dict (recipe).
        foundation_summary: Human-readable foundation data for context.

    Returns:
        A tuple of (raw_output_text, usage_dict).

    Raises:
        RuntimeError: If the agent returns an empty response.
    """
    agent = _create_or_update_agent()

    # Build input — Recipe + Foundation data ONLY (no Stage 1/2 text)
    input_message = f"""## Ad Strategy Recipe (from Stage 3)

{json.dumps(stage3_output, indent=2)}

## Relay Marketing Foundation Entities (from Cosmos DB)

{foundation_summary}

IMPORTANT: Write a brand-new, original Relay Human Cloud ad following the recipe above. Use ONLY Relay entity data. Do NOT paraphrase any reference transcript.
"""

    logger.info("Running Stage 4 agent (%d chars input)...", len(input_message))

    response = openai_client.responses.create(
        extra_body={
            "agent_reference": {
                "name": agent.name,
                "type": "agent_reference",
            }
        },
        input=input_message,
    )

    raw_output = response.output_text
    if not raw_output or not raw_output.strip():
        raise RuntimeError("Stage 4 agent returned an empty response.")

    usage = _extract_usage(response)
    logger.info(
        "Stage 4 agent returned %d chars | Tokens: in=%d, out=%d, total=%d",
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
            if usage["total_tokens"] == 0:
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    except Exception as e:
        logger.warning("Could not extract token usage: %s", e)
    return usage

