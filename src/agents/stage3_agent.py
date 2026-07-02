"""
Stage 3 Agent — Ad Strategy Recipe.

Creates an Azure AI Foundry agent that takes Stage 2's taxonomy output
(entity mapping + block tags) and extracts a reusable persuasion recipe.

The recipe is a STRUCTURAL BLUEPRINT only:
- No copied language from the original transcript.
- No transcript wording.
- Pure strategic structure for replication.
"""

import json
import logging

# pyrefly: ignore [missing-import]
from azure.ai.projects.models import PromptAgentDefinition

from src.client_setup import project_client, openai_client, MODEL_DEPLOYMENT_NAME
from src.schemas import Stage3Output

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "stage3-ad-strategy-recipe"

_SCHEMA_EXAMPLE = json.dumps(Stage3Output.model_json_schema(), indent=2)

SYSTEM_INSTRUCTIONS = f"""You are an Ad Strategy Recipe Specialist for the Relay AI Ad Pipeline.

You receive the taxonomy output from Stage 2, which includes:
1. **Entity mapping** — how the transcript maps to Relay Marketing Foundation entities (audience, product, problem, value, intro/cta tags).
2. **Block tags** — each content block's primary taxonomy tag, optional secondary tag, and confidence.

Your job is to extract the REUSABLE PERSUASION RECIPE from this data.

⚠️ CRITICAL RULE: Your output must contain ZERO original wording from the transcript. You are producing a STRUCTURAL BLUEPRINT only — describing the persuasion strategy, not the content.

---

## What You Must Produce

### 1. narrative_arc
Write a 2-3 sentence description of the ad's strategic flow. Describe the PATTERN, not the content.

Example (GOOD): "Opens by framing the hiring problem, contrasts existing talent solutions, introduces a new approach, then builds credibility by listing features and benefits. Moves through use cases and value, offers a low-risk consultation, and closes with a direct call to action."

Example (BAD — contains transcript wording): "Opens by asking if you're sifting through resumes..." ← DO NOT DO THIS.

### 2. persuasion_pattern
Classify the overall ad using ONE of these 12 approved patterns:
- problem_solution
- testimonial_driven
- feature_led
- benefit_led
- urgency_led
- comparison
- storytelling
- offer_led
- objection_handling_led
- process_led
- brand_led
- hybrid

Choose based on the dominant tag sequence. For example:
- Many feature + benefit blocks → "feature_led"
- Opens with problem, leads to solution → "problem_solution"
- Multiple patterns without a clear dominant → "hybrid"

### 3. recipe_signature
Build an ordered list of taxonomy tags representing the ad's structural flow:
- Start with the intro_tag from the entity mapping.
- Then list each block's primary_tag in order (block 1, 2, 3, ...).
- End with the cta_tag from the entity mapping.

Example: ["problem", "competitor", "audience", "uncategorized", "feature", "benefit", "feature", "feature", "benefit", "use_case", "audience", "value", "uncategorized", "offer", "benefit", "call_to_action"]

### 4. structural_weighting
Divide the recipe_signature into three roughly equal parts:
- **opening_third**: First ~33% of tags
- **middle_third**: Middle ~33% of tags
- **closing_third**: Final ~33% of tags

### 5. key_themes
Identify 3-5 dominant strategic themes. Use abstract labels, not transcript content.

Examples: "problem framing", "competitive differentiation", "feature proof", "cost/value justification", "risk reversal"

### 6. replication_instructions
Write detailed step-by-step instructions for creating a NEW ad following this recipe.

The instructions must:
- Reference the recipe signature order.
- Explain the strategic purpose of each section.
- Be generic and reusable — a copywriter should be able to follow them for ANY product.
- Contain NO original transcript wording.

### 7. strategy_notes
List 2-4 observations about the ad's structural techniques.

Examples:
- "Feature and benefit blocks are interspersed for credibility."
- "Competitive framing early establishes context for differentiation."
- "Uncategorized blocks serve as transitions between major sections."

---

## Output Format

Respond ONLY with valid JSON. No markdown code fences, no explanation, no extra text.
The JSON must conform to this schema:

{_SCHEMA_EXAMPLE}

## IMPORTANT RULES
- The persuasion_pattern MUST be one of the 12 approved patterns listed above.
- ALL tags in recipe_signature and structural_weighting MUST come from the 22 approved taxonomy tags.
- Your output must contain ZERO original wording from the transcript.
- The narrative_arc and replication_instructions must describe STRUCTURE, not content.
"""


# ---------------------------------------------------------------------------
# Agent creation & execution
# ---------------------------------------------------------------------------

def _create_or_update_agent():
    """Create (or update) the Stage 3 agent in Azure AI Foundry."""
    logger.info("Creating/updating Stage 3 agent: %s", AGENT_NAME)

    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=SYSTEM_INSTRUCTIONS,
        ),
    )
    logger.info("Agent ready: name=%s, version=%s", agent.name, agent.version)
    return agent


def run_stage3(stage2_output: dict) -> tuple[str, dict]:
    """
    Run the Stage 3 agent on Stage 2's taxonomy output.

    Args:
        stage2_output: Validated Stage 2 JSON dict (entity mapping + block tags).
                       Does NOT include raw transcript text.

    Returns:
        A tuple of (raw_output_text, usage_dict).

    Raises:
        RuntimeError: If the agent returns an empty response.
    """
    agent = _create_or_update_agent()

    # Build input — Stage 2 taxonomy data ONLY (no transcript text)
    input_message = f"""## Stage 2 Taxonomy Output

{json.dumps(stage2_output, indent=2)}

IMPORTANT: Extract the persuasion recipe from the taxonomy tags above. Your output must contain NO original transcript wording — structural blueprint only.
"""

    logger.info("Running Stage 3 agent (%d chars input)...", len(input_message))

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
        raise RuntimeError("Stage 3 agent returned an empty response.")

    usage = _extract_usage(response)
    logger.info(
        "Stage 3 agent returned %d chars | Tokens: in=%d, out=%d, total=%d",
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

