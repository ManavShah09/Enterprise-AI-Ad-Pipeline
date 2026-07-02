"""
Stage 2 Agent — Taxonomy Tagging.

Creates an Azure AI Foundry agent that takes Stage 1's structured transcript
and the live Relay Marketing Foundation data, then produces:

Phase 1: Entity mapping to Relay's controlled taxonomy and real entities.
Phase 2: Per-block taxonomy tagging with 22 primary tags, optional secondary
         tags, confidence levels, and review flags.

The agent is instructed to return ONLY valid JSON matching the Stage2Output schema.
"""

import json
import logging

# pyrefly: ignore [missing-import]
from azure.ai.projects.models import PromptAgentDefinition

from src.client_setup import project_client, openai_client, MODEL_DEPLOYMENT_NAME
from src.schemas import Stage2Output

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent configuration
# ---------------------------------------------------------------------------

AGENT_NAME = "stage2-taxonomy-tagging"

_SCHEMA_EXAMPLE = json.dumps(Stage2Output.model_json_schema(), indent=2)

# ---------------------------------------------------------------------------
# System instructions (static portion)
# ---------------------------------------------------------------------------

SYSTEM_INSTRUCTIONS_TEMPLATE = """You are a Taxonomy Tagging Specialist for the Relay AI Ad Pipeline.

You will receive TWO inputs:
1. A structured transcript (from Stage 1) containing: intro, content_blocks, and cta.
2. The live Relay Marketing Foundation entities from the database.

You must produce a JSON output with TWO phases.

---

## PHASE 1: Entity Mapping

Map the transcript to the Relay Marketing Foundation using the ACTUAL ENTITY NAMES provided in the foundation data.

⚠️ CRITICAL: For each field below, you must use an actual entity NAME from the foundation data lists — NOT the category/label name. For example:
- ✅ CORRECT: "audience": "Staff Augmentation / Staff Hosting"  (this is an actual entity name)
- ❌ WRONG:   "audience": "MarketingAudience"  (this is the category label, NOT an entity name)
- ✅ CORRECT: "product": "Staff Augmentation"  (actual entity name)
- ❌ WRONG:   "product": "Product"  (this is the category label)

Look at the "Available values:" line under each category in the foundation data to find the correct entity names.

Fields to map:
- **marketing_foundation**: Pick from the MarketingFoundation entities. Usually "Relay Human Cloud".
- **audience**: Pick the best matching entity NAME from the MarketingAudience list.
- **product**: Pick the best matching entity NAME from the Product list.
- **product_messaging**: Pick the best matching entity NAME from the ProductMessaging list.
- **icp**: Pick the best matching entity NAME from the ICPModel list. Use "Not specified" if none match the transcript.
- **mapped_problem**: Pick the ProblemValue entity NAME that best represents the PROBLEM described in the transcript. If no exact match, predict the closest one.
- **mapped_value**: Pick the ProblemValue entity NAME that best represents the VALUE/solution described in the transcript. If no exact match, predict the closest one.
- **intro_tag**: Classify the intro section with one of the 22 taxonomy tags below.
- **intro_tag_confidence**: Your confidence level (high/medium/low).
- **cta_tag**: Classify the CTA section with one of the 22 taxonomy tags below.
- **cta_tag_confidence**: Your confidence level (high/medium/low).

---

## PHASE 2: Block Tagging

For EACH content block from Stage 1, assign taxonomy tags.

### The 22 Primary Taxonomy Tags

**audience** — Identifies who the message is intended for. Use when the text mentions a target group, role, industry, department, or buyer persona.

**problem** — Describes a pain point, challenge, inefficiency, or unmet need. Use when the text highlights what is difficult, costly, slow, risky, or frustrating.

**value** — Communicates the overall business outcome or transformation delivered. Use when the text describes a broad positive result without focusing on specific features.

**product** — Describes what the company sells or provides. Use when the text explains the solution itself.

**product_messaging** — Strategic narrative or positioning language used to describe the product. Use when the text communicates how the product should be perceived rather than what it literally is.

**feature** — A specific capability, characteristic, or attribute of the product. Use when the text describes what the product has, includes, or does.

**benefit** — The advantage or outcome a customer receives from a feature. Use when the text answers "What's in it for the customer?"

**differentiator** — A unique aspect that distinguishes the offering from alternatives. Use when the text highlights uniqueness or superiority.

**use_case** — A specific scenario where the product is applied. Use when the text describes how customers use the solution.

**value_driver** — A measurable source of business value. Use when the text references cost savings, revenue growth, efficiency, productivity, speed, or ROI.

**marketing_trigger** — Language designed to create interest, urgency, curiosity, or FOMO. Use when the text motivates engagement or attention.

**icp** — The Ideal Customer Profile (best-fit customer). Use when the text describes company size, industry, maturity, or characteristics of the ideal buyer.

**icp_experience** — The situation, stage, or challenge currently experienced by the ICP. Use when the text describes what the ideal customer is going through.

**competitor** — References competitors or competing solutions. Use when the text compares against alternative providers, methods, or products.

**brand_positioning** — How the brand wants to be perceived in the market. Use when the text communicates trust, category leadership, expertise, or market position.

**social_proof** — Evidence that others trust, use, or endorse the solution. Use when the text mentions customers, testimonials, reviews, awards, or statistics.

**objection_handling** — Addresses common concerns, risks, or reasons someone might hesitate. Use when the text reduces fear, uncertainty, or perceived risk.

**process_descriptor** — Explains how the service, workflow, or methodology operates. Use when the text describes steps, processes, onboarding, or operations.

**offer** — A specific commercial proposal or incentive. Use when the text presents something being offered.

**call_to_action** — A direct instruction encouraging the reader to take action. Use when the text starts with an action verb or explicitly requests an action.

**urgency** — Creates time pressure or scarcity. Use when the text references deadlines, limited availability, or immediate action.

**uncategorized** — Does not clearly fit any other taxonomy category. Use only when the text is generic, informational, or lacks a clear marketing function.

### Classification Priority Rules

When multiple tags seem applicable, use these priorities:
- If describing a capability → feature
- If describing the customer outcome from a capability → benefit
- If describing measurable business impact → value_driver
- If describing broad business transformation → value
- If describing who the message targets → audience or icp
- If describing what the target customer is experiencing → icp_experience
- If describing the solution itself → product
- If describing the strategic narrative around the solution → product_messaging
- If addressing concerns or risk → objection_handling
- If requesting an action → call_to_action
- If creating scarcity or deadline pressure → urgency

Always assign the tag that best represents the PRIMARY purpose of the text.

### Secondary Tags
Assign a secondary tag ONLY when the block clearly contains information relevant to more than one tag. If the block has a single clear purpose, set secondary_tag to null.

### Confidence Levels
- **high**: The tag assignment is clear and unambiguous.
- **medium**: The tag is likely correct but the text could arguably fit another category.
- **low**: The tag is a best guess; the text is ambiguous or generic.

### Review Flags
For any block tagged as "uncategorized", you MUST add a review flag with:
- **block_number**: The block number
- **flag_reason**: Must be one of: low_confidence, uncategorized_block, entity_not_in_foundation, ambiguous_tag, missing_cta_context, unclear_intro, non_relay_company, weak_entity_match
- **explanation**: A brief explanation of why the flag was raised

Also flag blocks with "low" confidence using flag_reason "low_confidence".

### unmapped_count
Set this to the total number of blocks tagged as "uncategorized".

---

## Output Format

Respond ONLY with valid JSON. No markdown code fences, no explanation, no extra text.
The JSON must conform to this schema:

{schema}

## IMPORTANT RULES
- ALL tag values MUST come from the 22-tag set listed above. No custom tags.
- ALL confidence values MUST be: high, medium, or low.
- ALL flag_reason values MUST be from the 8 approved reasons listed above.
- Entity mapping values should match entities from the foundation data provided.
- For text_truncated, use the first ~80 characters of the block text.
"""


# ---------------------------------------------------------------------------
# Agent creation & execution
# ---------------------------------------------------------------------------

def _build_instructions(foundation_summary: str) -> str:
    """Build the full system instructions with the schema and foundation data."""
    return SYSTEM_INSTRUCTIONS_TEMPLATE.format(schema=_SCHEMA_EXAMPLE)


def _create_or_update_agent(foundation_summary: str):
    """Create (or update) the Stage 2 agent in Azure AI Foundry."""
    logger.info("Creating/updating Stage 2 agent: %s", AGENT_NAME)

    instructions = _build_instructions(foundation_summary)

    agent = project_client.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=MODEL_DEPLOYMENT_NAME,
            instructions=instructions,
        ),
    )
    logger.info("Agent ready: name=%s, version=%s", agent.name, agent.version)
    return agent


def run_stage2(stage1_output: dict, foundation_data: dict, foundation_summary: str) -> tuple[str, dict]:
    """
    Run the Stage 2 agent on the Stage 1 output with foundation data context.

    Args:
        stage1_output:      Validated Stage 1 JSON dict.
        foundation_data:    Raw foundation data from Cosmos DB.
        foundation_summary: Human-readable summary for the prompt.

    Returns:
        A tuple of (raw_output_text, usage_dict).

    Raises:
        RuntimeError: If the agent returns an empty response.
    """
    # Ensure the agent exists
    agent = _create_or_update_agent(foundation_summary)

    # Build the input message combining Stage 1 output and foundation context
    input_message = f"""## Stage 1 Structured Transcript

{json.dumps(stage1_output, indent=2)}

## Relay Marketing Foundation Entities (from Cosmos DB)

{foundation_summary}
"""

    logger.info("Running Stage 2 agent (%d chars input)...", len(input_message))

    # Generate a response using the agent
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
        raise RuntimeError("Stage 2 agent returned an empty response.")

    usage = _extract_usage(response)
    logger.info(
        "Stage 2 agent returned %d chars | Tokens: in=%d, out=%d, total=%d",
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

