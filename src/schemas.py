"""
Pydantic schemas defining the JSON contracts for each pipeline stage.

These schemas are used by the Orchestrator to validate that each agent's
output conforms to the expected structure before passing it downstream.
"""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Approved Controlled Vocabularies (from Problem Statement)
# ---------------------------------------------------------------------------

PRIMARY_TAXONOMY_TAGS: frozenset[str] = frozenset([
    "audience", "problem", "value", "product", "product_messaging",
    "feature", "benefit", "differentiator", "use_case", "value_driver",
    "marketing_trigger", "icp", "icp_experience", "competitor",
    "brand_positioning", "social_proof", "objection_handling",
    "process_descriptor", "offer", "call_to_action", "urgency",
    "uncategorized",
])

CONFIDENCE_LEVELS: frozenset[str] = frozenset(["high", "medium", "low"])

REVIEW_FLAG_REASONS: frozenset[str] = frozenset([
    "low_confidence", "uncategorized_block", "entity_not_in_foundation",
    "ambiguous_tag", "missing_cta_context", "unclear_intro",
    "non_relay_company", "weak_entity_match",
])

PERSUASION_PATTERNS: frozenset[str] = frozenset([
    "problem_solution", "testimonial_driven", "feature_led",
    "benefit_led", "urgency_led", "comparison", "storytelling",
    "offer_led", "objection_handling_led", "process_led",
    "brand_led", "hybrid",
])


# ---------------------------------------------------------------------------
# Stage 1: Transcript Structuring
# ---------------------------------------------------------------------------

class ContentBlock(BaseModel):
    """A single numbered content block from the structured transcript."""

    block_number: int = Field(
        ...,
        description="Sequential block number starting from 1.",
    )
    text: str = Field(
        ...,
        description="The full text content of this block.",
    )
    summary: str = Field(
        ...,
        description="A brief one-line summary of what this block conveys.",
    )


class Stage1Output(BaseModel):
    """
    The validated output contract for Stage 1 — Transcript Structuring.

    The Stage 1 agent must produce JSON that exactly matches this schema:
    - intro:          The opening hook / introduction of the advertisement.
    - content_blocks: A list of numbered content sections.
    - cta:            The closing Call-to-Action.
    """

    intro: str = Field(
        ...,
        description="The opening hook or introduction of the advertisement.",
    )
    content_blocks: list[ContentBlock] = Field(
        ...,
        description="Ordered list of content blocks extracted from the transcript.",
        min_length=1,
    )
    cta: str = Field(
        ...,
        description="The closing Call-to-Action of the advertisement.",
    )


# ---------------------------------------------------------------------------
# Stage 2: Taxonomy Tagging
# ---------------------------------------------------------------------------

class EntityMapping(BaseModel):
    """
    Phase 1 output — Maps the transcript to Relay Marketing Foundation entities.

    Entity values should come from the live Cosmos DB graph.
    Mapped Problem and Mapped Value are predicted by the agent.
    """

    marketing_foundation: str = Field(
        ...,
        description="The Relay Marketing Foundation name (e.g. 'Relay Human Cloud').",
    )
    audience: str = Field(
        ...,
        description="Target audience from the foundation (e.g. 'Staff Augmentation / Staff Hosting').",
    )
    product: str = Field(
        ...,
        description="Relay product that best matches the transcript.",
    )
    product_messaging: str = Field(
        ...,
        description="Product messaging variant from the foundation.",
    )
    icp: str = Field(
        ...,
        description="Ideal Customer Profile. Use 'Not specified' if unclear.",
    )
    mapped_problem: str = Field(
        ...,
        description="Predicted problem from ProblemValue entities (e.g. 'Escalating Labor Costs').",
    )
    mapped_value: str = Field(
        ...,
        description="Predicted value proposition from ProblemValue entities (e.g. 'Reduce Labor Costs').",
    )
    intro_tag: str = Field(
        ...,
        description="Primary taxonomy tag for the intro section.",
    )
    intro_tag_confidence: str = Field(
        ...,
        description="Confidence level for the intro tag: high, medium, or low.",
    )
    cta_tag: str = Field(
        ...,
        description="Primary taxonomy tag for the CTA section.",
    )
    cta_tag_confidence: str = Field(
        ...,
        description="Confidence level for the CTA tag: high, medium, or low.",
    )


class BlockTag(BaseModel):
    """Phase 2 output — Taxonomy tag for a single content block."""

    block_number: int = Field(
        ...,
        description="The block number from Stage 1 output.",
    )
    text_truncated: str = Field(
        ...,
        description="First ~80 characters of the block text for readability.",
    )
    primary_tag: str = Field(
        ...,
        description="Primary taxonomy tag from the 22-tag approved set.",
    )
    secondary_tag: str | None = Field(
        default=None,
        description="Optional secondary tag if the block spans two taxonomy categories.",
    )
    confidence: str = Field(
        ...,
        description="Confidence level: high, medium, or low.",
    )


class ReviewFlag(BaseModel):
    """A review flag raised for blocks that need human attention."""

    block_number: int = Field(
        ...,
        description="The block number this flag applies to.",
    )
    flag_reason: str = Field(
        ...,
        description="Reason code from the approved set of 8 review flag reasons.",
    )
    explanation: str = Field(
        ...,
        description="Human-readable explanation of why this flag was raised.",
    )


class Stage2Output(BaseModel):
    """
    The validated output contract for Stage 2 — Taxonomy Tagging.

    Contains:
    - entity_mapping:  Relay entity mapping (Phase 1)
    - block_tags:      Per-block taxonomy tags (Phase 2)
    - review_flags:    Flags for blocks needing review
    - unmapped_count:  Number of uncategorized blocks
    """

    entity_mapping: EntityMapping = Field(
        ...,
        description="Relay entity mapping from the Marketing Foundation.",
    )
    block_tags: list[BlockTag] = Field(
        ...,
        description="Taxonomy tags for each content block.",
        min_length=1,
    )
    review_flags: list[ReviewFlag] = Field(
        default_factory=list,
        description="Review flags for blocks needing human attention.",
    )
    unmapped_count: int = Field(
        ...,
        description="Count of blocks tagged as 'uncategorized'.",
    )


# ---------------------------------------------------------------------------
# Stage 3: Ad Strategy Recipe
# ---------------------------------------------------------------------------

class StructuralWeighting(BaseModel):
    """Divides the recipe signature into thirds for structural analysis."""

    opening_third: list[str] = Field(
        ...,
        description="Taxonomy tags in the first ~33% of the ad flow.",
    )
    middle_third: list[str] = Field(
        ...,
        description="Taxonomy tags in the middle ~33% of the ad flow.",
    )
    closing_third: list[str] = Field(
        ...,
        description="Taxonomy tags in the final ~33% of the ad flow.",
    )


class Stage3Output(BaseModel):
    """
    The validated output contract for Stage 3 — Ad Strategy Recipe.

    The recipe must contain STRUCTURE ONLY:
    - No copied language from the transcript.
    - No transcript wording.
    - Pure strategic blueprint for replication.
    """

    narrative_arc: str = Field(
        ...,
        description=(
            "A 2-3 sentence description of the strategic flow of the ad. "
            "Must NOT contain any original wording from the transcript."
        ),
    )
    persuasion_pattern: str = Field(
        ...,
        description="The dominant persuasion pattern from the 12 approved patterns.",
    )
    recipe_signature: list[str] = Field(
        ...,
        description=(
            "Ordered list of taxonomy tags representing the ad's structural flow. "
            "Includes intro_tag at start, block primary_tags in order, and cta_tag at end."
        ),
        min_length=3,
    )
    structural_weighting: StructuralWeighting = Field(
        ...,
        description="Tags divided into opening, middle, and closing thirds.",
    )
    key_themes: list[str] = Field(
        ...,
        description="Dominant strategic themes identified (e.g. 'problem framing', 'cost/value justification').",
        min_length=1,
    )
    replication_instructions: str = Field(
        ...,
        description=(
            "Step-by-step guide for writing a new ad following this recipe. "
            "Must be generic and reusable — no original transcript wording."
        ),
    )
    strategy_notes: list[str] = Field(
        ...,
        description="Observations about the ad's structural patterns and techniques.",
        min_length=1,
    )


# ---------------------------------------------------------------------------
# Stage 4: Ad Creative Generation
# ---------------------------------------------------------------------------

class ScriptBlock(BaseModel):
    """A single block in the newly generated Relay ad script."""

    block_number: int = Field(
        ...,
        description="Sequential block number starting from 1.",
    )
    text: str = Field(
        ...,
        description="The written content for this block.",
    )
    intended_tag: str = Field(
        ...,
        description="The taxonomy tag this block is intended to fulfill.",
    )


class Stage4Output(BaseModel):
    """
    The validated output contract for Stage 4 — Ad Creative Generation.

    The ad script must be:
    - Completely original content for Relay Human Cloud.
    - NOT a paraphrase of any reference transcript.
    - Generated from the recipe + approved Relay content only.
    """

    relay_ad_script: str = Field(
        ...,
        description="The complete, brand-new Relay Human Cloud advertisement script as continuous text.",
    )
    script_blocks: list[ScriptBlock] = Field(
        ...,
        description="Structured breakdown of the script into taxonomy-tagged blocks.",
        min_length=1,
    )
    generation_notes: str = Field(
        ...,
        description="Notes about how the script was derived from the recipe and foundation data.",
    )


