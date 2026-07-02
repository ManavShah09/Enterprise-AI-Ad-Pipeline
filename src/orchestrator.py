"""
Orchestrator — Programmatic Pipeline Coordinator.

This module is the central controller of the Relay AI Ad Pipeline.
It is NOT an LLM agent — it is pure Python logic responsible for:

1. Receiving the raw transcript from the user.
2. Routing it to the appropriate stage agent.
3. Validating each agent's JSON output against Pydantic schemas.
4. Enforcing controlled vocabulary constraints (approved tag sets).
5. Enforcing data isolation (Stage 1/2 text never reaches Stage 4).
6. Tracking token usage across all agent calls.
7. Halting the pipeline on any failure and producing a clear error report.
8. Generating a human-readable Markdown report of the pipeline run.

Per the Problem Statement:
- The orchestrator must NEVER write ad copy or reclassify taxonomy tags.
- All content generation occurs inside the four stage agents.
- Any value outside the approved controlled vocabularies must be rejected.
"""

import json
import logging
import traceback
from datetime import datetime, timezone

from pydantic import ValidationError

from src.agents.stage1_agent import run_stage1
from src.agents.stage2_agent import run_stage2
from src.agents.stage3_agent import run_stage3
from src.agents.stage4_agent import run_stage4
from src.schemas import (
    Stage1Output,
    Stage2Output,
    Stage3Output,
    Stage4Output,
    PRIMARY_TAXONOMY_TAGS,
    CONFIDENCE_LEVELS,
    REVIEW_FLAG_REASONS,
    PERSUASION_PATTERNS,
)
from src.services.cosmos import get_foundation_data, get_foundation_summary

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token usage tracker
# ---------------------------------------------------------------------------

def _empty_usage() -> dict:
    """Return an empty usage dict."""
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def _add_usage(accumulator: dict, stage_usage: dict):
    """Add a stage's usage to the accumulator in-place."""
    accumulator["input_tokens"] += stage_usage.get("input_tokens", 0)
    accumulator["output_tokens"] += stage_usage.get("output_tokens", 0)
    accumulator["total_tokens"] += stage_usage.get("total_tokens", 0)


# ---------------------------------------------------------------------------
# Pipeline result structure
# ---------------------------------------------------------------------------

def _make_result(
    status: str,
    stage_1_output: dict | None = None,
    stage_2_output: dict | None = None,
    stage_3_output: dict | None = None,
    stage_4_output: dict | None = None,
    report: str = "",
    error: dict | None = None,
    token_usage: dict | None = None,
) -> dict:
    """Build the standardised pipeline result dict."""
    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage_1_output": stage_1_output,
        "stage_2_output": stage_2_output,
        "stage_3_output": stage_3_output,
        "stage_4_output": stage_4_output,
        "report": report,
        "error": error,
        "token_usage": token_usage or {},
    }


# ---------------------------------------------------------------------------
# Controlled vocabulary validation
# ---------------------------------------------------------------------------

def _validate_stage2_vocab(stage2: Stage2Output) -> list[str]:
    """Validate Stage 2 tags against approved vocabularies."""
    violations = []
    em = stage2.entity_mapping

    if em.intro_tag not in PRIMARY_TAXONOMY_TAGS:
        violations.append(f"intro_tag '{em.intro_tag}' is not in the 22 approved taxonomy tags.")
    if em.cta_tag not in PRIMARY_TAXONOMY_TAGS:
        violations.append(f"cta_tag '{em.cta_tag}' is not in the 22 approved taxonomy tags.")
    if em.intro_tag_confidence not in CONFIDENCE_LEVELS:
        violations.append(f"intro_tag_confidence '{em.intro_tag_confidence}' is not valid.")
    if em.cta_tag_confidence not in CONFIDENCE_LEVELS:
        violations.append(f"cta_tag_confidence '{em.cta_tag_confidence}' is not valid.")

    for bt in stage2.block_tags:
        if bt.primary_tag not in PRIMARY_TAXONOMY_TAGS:
            violations.append(f"Block {bt.block_number}: primary_tag '{bt.primary_tag}' is not approved.")
        if bt.secondary_tag and bt.secondary_tag not in PRIMARY_TAXONOMY_TAGS:
            violations.append(f"Block {bt.block_number}: secondary_tag '{bt.secondary_tag}' is not approved.")
        if bt.confidence not in CONFIDENCE_LEVELS:
            violations.append(f"Block {bt.block_number}: confidence '{bt.confidence}' is not valid.")

    for rf in stage2.review_flags:
        if rf.flag_reason not in REVIEW_FLAG_REASONS:
            violations.append(f"Review flag block {rf.block_number}: flag_reason '{rf.flag_reason}' is not approved.")

    return violations


def _validate_stage3_vocab(stage3: Stage3Output) -> list[str]:
    """Validate Stage 3 tags against approved vocabularies."""
    violations = []

    if stage3.persuasion_pattern not in PERSUASION_PATTERNS:
        violations.append(
            f"persuasion_pattern '{stage3.persuasion_pattern}' is not in the 12 approved patterns. "
            f"Must be one of: {sorted(PERSUASION_PATTERNS)}"
        )

    for i, tag in enumerate(stage3.recipe_signature):
        if tag not in PRIMARY_TAXONOMY_TAGS:
            violations.append(f"recipe_signature[{i}]: tag '{tag}' is not in the 22 approved taxonomy tags.")

    sw = stage3.structural_weighting
    for section_name, tags in [
        ("opening_third", sw.opening_third),
        ("middle_third", sw.middle_third),
        ("closing_third", sw.closing_third),
    ]:
        for tag in tags:
            if tag not in PRIMARY_TAXONOMY_TAGS:
                violations.append(f"structural_weighting.{section_name}: tag '{tag}' is not approved.")

    return violations


def _validate_stage4_vocab(stage4: Stage4Output) -> list[str]:
    """Validate Stage 4 tags against approved vocabularies."""
    violations = []

    for sb in stage4.script_blocks:
        if sb.intended_tag not in PRIMARY_TAXONOMY_TAGS:
            violations.append(
                f"script_block {sb.block_number}: intended_tag '{sb.intended_tag}' is not approved."
            )

    if not stage4.relay_ad_script.strip():
        violations.append("relay_ad_script is empty.")

    return violations


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _generate_token_usage_section(per_stage: dict, total: dict) -> str:
    """Generate the token usage section for the Markdown report."""
    lines = [
        "",
        "---",
        "",
        "## Token Usage Summary",
        "",
        "| Agent | Input Tokens | Output Tokens | Total Tokens |",
        "|-------|-------------|--------------|-------------|",
    ]

    stage_names = {
        "stage_1": "Stage 1: Structuring",
        "stage_2": "Stage 2: Taxonomy",
        "stage_3": "Stage 3: Recipe",
        "stage_4": "Stage 4: Creative",
    }

    for key, name in stage_names.items():
        usage = per_stage.get(key, _empty_usage())
        lines.append(
            f"| {name} | {usage['input_tokens']:,} | {usage['output_tokens']:,} | {usage['total_tokens']:,} |"
        )

    lines.append(
        f"| **TOTAL** | **{total['input_tokens']:,}** | **{total['output_tokens']:,}** | **{total['total_tokens']:,}** |"
    )
    lines.append("")

    return "\n".join(lines)


def _generate_full_report(
    stage1: Stage1Output,
    stage2: Stage2Output | None = None,
    stage3: Stage3Output | None = None,
    stage4: Stage4Output | None = None,
    per_stage_usage: dict | None = None,
    total_usage: dict | None = None,
) -> str:
    """Generate a comprehensive Markdown report for all completed stages."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    completed_stages = 1
    if stage2:
        completed_stages = 2
    if stage3:
        completed_stages = 3
    if stage4:
        completed_stages = 4

    if completed_stages == 4:
        status = "All Stages Complete ✅"
    else:
        status = f"Stage 1–{completed_stages} Complete ✅"

    block_summaries = "\n".join(
        f"  - **Block {b.block_number}:** {b.summary}"
        for b in stage1.content_blocks
    )

    report = f"""# Ad Pipeline Report

## Status: {status}

**Generated at:** {now}

---

### Stage 1: Transcript Structuring — ✅ SUCCESS

**Intro:**
> {stage1.intro}

**Content Blocks:** {len(stage1.content_blocks)} block(s) identified
{block_summaries}

**CTA:**
> {stage1.cta}
"""

    # Stage 2
    if stage2:
        em = stage2.entity_mapping
        report += f"""
---

### Stage 2: Taxonomy Tagging — ✅ SUCCESS

#### Entity Mapping

| Field | Value |
|-------|-------|
| Marketing Foundation | {em.marketing_foundation} |
| Audience | {em.audience} |
| Product | {em.product} |
| Product Messaging | {em.product_messaging} |
| ICP | {em.icp} |
| Mapped Problem | {em.mapped_problem} |
| Mapped Value | {em.mapped_value} |
| Intro tag | {em.intro_tag} (confidence: {em.intro_tag_confidence}) |
| CTA tag | {em.cta_tag} (confidence: {em.cta_tag_confidence}) |

#### Block Tags

| # | Text (truncated) | Primary tag | Secondary | Confidence |
|---|-----------------|-------------|-----------|------------|
"""
        for bt in stage2.block_tags:
            sec = bt.secondary_tag or "—"
            report += f"| {bt.block_number} | {bt.text_truncated} | {bt.primary_tag} | {sec} | {bt.confidence} |\n"

        if stage2.review_flags:
            report += f"\n#### Review Flags: {len(stage2.review_flags)}\n\n"
            for rf in stage2.review_flags:
                report += f"- **Block {rf.block_number}**: {rf.flag_reason} — {rf.explanation}\n"
            report += f"\n**Unmapped count:** {stage2.unmapped_count}\n"
        else:
            report += "\n#### Review Flags: 0\n\nNo review flags raised.\n"
    else:
        report += "\n---\n\n### Stage 2: Taxonomy Tagging — ⏳ Pending\n"

    # Stage 3
    if stage3:
        sig_str = " + ".join(stage3.recipe_signature)
        themes_str = "\n".join(f"  - {t}" for t in stage3.key_themes)
        notes_str = "\n".join(f"  - {n}" for n in stage3.strategy_notes)
        opening = ", ".join(stage3.structural_weighting.opening_third)
        middle = ", ".join(stage3.structural_weighting.middle_third)
        closing = ", ".join(stage3.structural_weighting.closing_third)

        report += f"""
---

### Stage 3: Ad Strategy Recipe — ✅ SUCCESS

**Narrative Arc:**
> {stage3.narrative_arc}

**Persuasion Pattern:** `{stage3.persuasion_pattern}`

**Recipe Signature:**
`{sig_str}`

**Structural Weighting:**
- **Opening third:** {opening}
- **Middle third:** {middle}
- **Closing third:** {closing}

**Key Themes:**
{themes_str}

**Replication Instructions:**
> {stage3.replication_instructions}

**Strategy Notes:**
{notes_str}
"""
    else:
        report += "\n---\n\n### Stage 3: Ad Strategy Recipe — ⏳ Pending\n"

    # Stage 4
    if stage4:
        blocks_table = "| # | Intended Tag | Text (truncated) |\n|---|---|---|\n"
        for sb in stage4.script_blocks:
            truncated = sb.text[:80] + "…" if len(sb.text) > 80 else sb.text
            blocks_table += f"| {sb.block_number} | {sb.intended_tag} | {truncated} |\n"

        report += f"""
---

### Stage 4: Ad Creative Generation — ✅ SUCCESS

**New Relay Human Cloud Ad Script:**

> {stage4.relay_ad_script}

**Script Structure:**
{blocks_table}

**Generation Notes:**
> {stage4.generation_notes}
"""
    else:
        report += "\n---\n\n### Stage 4: Ad Creative Generation — ⏳ Pending\n"

    # Token usage section
    if per_stage_usage and total_usage:
        report += _generate_token_usage_section(per_stage_usage, total_usage)

    return report


def _generate_failure_report(
    stage: int,
    stage_name: str,
    reason: str,
    raw_output: str | None = None,
    stage1: Stage1Output | None = None,
    stage2: Stage2Output | None = None,
    stage3: Stage3Output | None = None,
    per_stage_usage: dict | None = None,
    total_usage: dict | None = None,
) -> str:
    """Generate a Markdown report for a pipeline failure."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    raw_section = ""
    if raw_output:
        truncated = raw_output[:2000]
        if len(raw_output) > 2000:
            truncated += "\n... (truncated)"
        raw_section = f"""

**Raw Agent Output:**
```
{truncated}
```"""

    prior_section = ""
    if stage1 and stage > 1:
        prior_section += f"\n### Stage 1: Transcript Structuring — ✅ SUCCESS\n"
        prior_section += f"**Blocks:** {len(stage1.content_blocks)} | **CTA:** {stage1.cta[:80]}...\n"
    if stage2 and stage > 2:
        prior_section += f"\n### Stage 2: Taxonomy Tagging — ✅ SUCCESS\n"
        prior_section += f"**Block tags:** {len(stage2.block_tags)} | **Pattern:** {stage2.entity_mapping.intro_tag}\n"
    if stage3 and stage > 3:
        prior_section += f"\n### Stage 3: Ad Strategy Recipe — ✅ SUCCESS\n"
        prior_section += f"**Pattern:** {stage3.persuasion_pattern}\n"

    # Token usage section
    token_section = ""
    if per_stage_usage and total_usage:
        token_section = _generate_token_usage_section(per_stage_usage, total_usage)

    return f"""# Ad Pipeline Report

## Status: FAILED ❌

**Generated at:** {now}

---
{prior_section}
### Stage {stage}: {stage_name} — ❌ FAILED

**Reason:** {reason}
{raw_section}

---

### Stages {stage + 1}–4: Not executed (pipeline halted at Stage {stage})
{token_section}
"""


# ---------------------------------------------------------------------------
# JSON cleaning helper
# ---------------------------------------------------------------------------

def _clean_llm_json(raw: str) -> str:
    """Strip markdown code fences that LLMs sometimes add around JSON."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        cleaned = "\n".join(lines)
    return cleaned


# ---------------------------------------------------------------------------
# Main pipeline execution
# ---------------------------------------------------------------------------

def run_pipeline(transcript: str) -> dict:
    """
    Execute the full Relay AI Ad Pipeline (Stages 1–4).

    Args:
        transcript: The raw advertisement transcript text.

    Returns:
        A dict containing:
        - status:         "success" or "failed"
        - timestamp:      ISO-8601 UTC timestamp
        - stage_1_output: Validated Stage 1 JSON (or None)
        - stage_2_output: Validated Stage 2 JSON (or None)
        - stage_3_output: Validated Stage 3 JSON (or None)
        - stage_4_output: Validated Stage 4 JSON (or None)
        - report:         Markdown report string
        - error:          Error details dict (or None on success)
        - token_usage:    Per-stage and total token usage
    """

    # Token usage accumulators
    per_stage_usage = {}
    total_usage = _empty_usage()

    # ------------------------------------------------------------------
    # Step 0: Validate input
    # ------------------------------------------------------------------
    if not transcript or not transcript.strip():
        reason = "Input transcript is empty or contains only whitespace."
        logger.error("Step 0 failed: %s", reason)
        return _make_result(
            status="failed",
            report=_generate_failure_report(stage=0, stage_name="Input Validation", reason=reason),
            error={"stage": 0, "reason": reason},
            token_usage={"per_stage": per_stage_usage, "total": total_usage},
        )

    transcript = transcript.strip()
    logger.info("Pipeline started. Transcript length: %d chars", len(transcript))

    # ------------------------------------------------------------------
    # Stage 1: Transcript Structuring
    # ------------------------------------------------------------------
    raw_stage1: str | None = None
    stage1_validated: Stage1Output | None = None

    try:
        logger.info("=" * 60)
        logger.info("=== Stage 1: Transcript Structuring ===")
        logger.info("=" * 60)

        raw_stage1, stage1_usage = run_stage1(transcript)
        per_stage_usage["stage_1"] = stage1_usage
        _add_usage(total_usage, stage1_usage)

        cleaned = _clean_llm_json(raw_stage1)
        stage1_validated = Stage1Output.model_validate_json(cleaned)
        logger.info("Stage 1 validation passed: %d content blocks.", len(stage1_validated.content_blocks))

    except (ValidationError, json.JSONDecodeError, RuntimeError, Exception) as e:
        reason = f"Stage 1 failed: {type(e).__name__}: {e}"
        logger.error(reason)
        if not isinstance(e, (ValidationError, json.JSONDecodeError, RuntimeError)):
            logger.error(traceback.format_exc())
        return _make_result(
            status="failed",
            report=_generate_failure_report(
                stage=1, stage_name="Transcript Structuring",
                reason=reason, raw_output=raw_stage1,
                per_stage_usage=per_stage_usage, total_usage=total_usage,
            ),
            error={"stage": 1, "reason": str(e)},
            token_usage={"per_stage": per_stage_usage, "total": total_usage},
        )

    stage1_dict = stage1_validated.model_dump()

    # ------------------------------------------------------------------
    # Stage 2: Taxonomy Tagging
    # ------------------------------------------------------------------
    raw_stage2: str | None = None
    stage2_validated: Stage2Output | None = None

    try:
        logger.info("=" * 60)
        logger.info("=== Stage 2: Taxonomy Tagging ===")
        logger.info("=" * 60)

        logger.info("Fetching Relay Marketing Foundation data...")
        foundation_data = get_foundation_data()
        foundation_summary = get_foundation_summary(foundation_data)
        logger.info("Foundation data ready (%d chars summary).", len(foundation_summary))

        from src.services.cosmos import debug_dump_foundation
        logger.info("Foundation data debug dump:\n%s", debug_dump_foundation(foundation_data))

        raw_stage2, stage2_usage = run_stage2(stage1_dict, foundation_data, foundation_summary)
        per_stage_usage["stage_2"] = stage2_usage
        _add_usage(total_usage, stage2_usage)

        cleaned = _clean_llm_json(raw_stage2)
        stage2_validated = Stage2Output.model_validate_json(cleaned)
        logger.info("Stage 2 schema validation passed: %d block tags.", len(stage2_validated.block_tags))

        violations = _validate_stage2_vocab(stage2_validated)
        if violations:
            reason = "Stage 2 controlled vocabulary violations:\n" + "\n".join(f"  - {v}" for v in violations)
            logger.error(reason)
            return _make_result(
                status="failed",
                stage_1_output=stage1_dict,
                report=_generate_failure_report(
                    stage=2, stage_name="Taxonomy Tagging",
                    reason=reason, raw_output=raw_stage2, stage1=stage1_validated,
                    per_stage_usage=per_stage_usage, total_usage=total_usage,
                ),
                error={"stage": 2, "reason": reason},
                token_usage={"per_stage": per_stage_usage, "total": total_usage},
            )
        logger.info("Stage 2 controlled vocabulary validation passed.")

    except (ValidationError, json.JSONDecodeError, RuntimeError, Exception) as e:
        reason = f"Stage 2 failed: {type(e).__name__}: {e}"
        logger.error(reason)
        if not isinstance(e, (ValidationError, json.JSONDecodeError, RuntimeError)):
            logger.error(traceback.format_exc())
        return _make_result(
            status="failed",
            stage_1_output=stage1_dict,
            report=_generate_failure_report(
                stage=2, stage_name="Taxonomy Tagging",
                reason=reason, raw_output=raw_stage2, stage1=stage1_validated,
                per_stage_usage=per_stage_usage, total_usage=total_usage,
            ),
            error={"stage": 2, "reason": str(e)},
            token_usage={"per_stage": per_stage_usage, "total": total_usage},
        )

    stage2_dict = stage2_validated.model_dump()

    # ------------------------------------------------------------------
    # Stage 3: Ad Strategy Recipe
    # ------------------------------------------------------------------
    raw_stage3: str | None = None
    stage3_validated: Stage3Output | None = None

    try:
        logger.info("=" * 60)
        logger.info("=== Stage 3: Ad Strategy Recipe ===")
        logger.info("=" * 60)

        raw_stage3, stage3_usage = run_stage3(stage2_dict)
        per_stage_usage["stage_3"] = stage3_usage
        _add_usage(total_usage, stage3_usage)

        cleaned = _clean_llm_json(raw_stage3)
        stage3_validated = Stage3Output.model_validate_json(cleaned)
        logger.info(
            "Stage 3 schema validation passed: pattern=%s, signature=%d tags.",
            stage3_validated.persuasion_pattern,
            len(stage3_validated.recipe_signature),
        )

        violations = _validate_stage3_vocab(stage3_validated)
        if violations:
            reason = "Stage 3 controlled vocabulary violations:\n" + "\n".join(f"  - {v}" for v in violations)
            logger.error(reason)
            return _make_result(
                status="failed",
                stage_1_output=stage1_dict,
                stage_2_output=stage2_dict,
                report=_generate_failure_report(
                    stage=3, stage_name="Ad Strategy Recipe",
                    reason=reason, raw_output=raw_stage3,
                    stage1=stage1_validated, stage2=stage2_validated,
                    per_stage_usage=per_stage_usage, total_usage=total_usage,
                ),
                error={"stage": 3, "reason": reason},
                token_usage={"per_stage": per_stage_usage, "total": total_usage},
            )
        logger.info("Stage 3 controlled vocabulary validation passed.")

    except (ValidationError, json.JSONDecodeError, RuntimeError, Exception) as e:
        reason = f"Stage 3 failed: {type(e).__name__}: {e}"
        logger.error(reason)
        if not isinstance(e, (ValidationError, json.JSONDecodeError, RuntimeError)):
            logger.error(traceback.format_exc())
        return _make_result(
            status="failed",
            stage_1_output=stage1_dict,
            stage_2_output=stage2_dict,
            report=_generate_failure_report(
                stage=3, stage_name="Ad Strategy Recipe",
                reason=reason, raw_output=raw_stage3,
                stage1=stage1_validated, stage2=stage2_validated,
                per_stage_usage=per_stage_usage, total_usage=total_usage,
            ),
            error={"stage": 3, "reason": str(e)},
            token_usage={"per_stage": per_stage_usage, "total": total_usage},
        )

    stage3_dict = stage3_validated.model_dump()

    # ------------------------------------------------------------------
    # Stage 4: Ad Creative Generation
    #
    # DATA ISOLATION: Stage 4 receives ONLY:
    #   - stage3_output (recipe — structural blueprint)
    #   - foundation_summary (Relay entity data)
    # ------------------------------------------------------------------
    raw_stage4: str | None = None
    stage4_validated: Stage4Output | None = None

    try:
        logger.info("=" * 60)
        logger.info("=== Stage 4: Ad Creative Generation ===")
        logger.info("=" * 60)
        logger.info("DATA ISOLATION: Passing ONLY recipe + foundation data to Stage 4.")

        raw_stage4, stage4_usage = run_stage4(stage3_dict, foundation_summary)
        per_stage_usage["stage_4"] = stage4_usage
        _add_usage(total_usage, stage4_usage)

        cleaned = _clean_llm_json(raw_stage4)
        stage4_validated = Stage4Output.model_validate_json(cleaned)
        logger.info(
            "Stage 4 schema validation passed: %d script blocks.",
            len(stage4_validated.script_blocks),
        )

        violations = _validate_stage4_vocab(stage4_validated)
        if violations:
            reason = "Stage 4 controlled vocabulary violations:\n" + "\n".join(f"  - {v}" for v in violations)
            logger.error(reason)
            return _make_result(
                status="failed",
                stage_1_output=stage1_dict,
                stage_2_output=stage2_dict,
                stage_3_output=stage3_dict,
                report=_generate_failure_report(
                    stage=4, stage_name="Ad Creative Generation",
                    reason=reason, raw_output=raw_stage4,
                    stage1=stage1_validated, stage2=stage2_validated, stage3=stage3_validated,
                    per_stage_usage=per_stage_usage, total_usage=total_usage,
                ),
                error={"stage": 4, "reason": reason},
                token_usage={"per_stage": per_stage_usage, "total": total_usage},
            )
        logger.info("Stage 4 controlled vocabulary validation passed.")

    except (ValidationError, json.JSONDecodeError, RuntimeError, Exception) as e:
        reason = f"Stage 4 failed: {type(e).__name__}: {e}"
        logger.error(reason)
        if not isinstance(e, (ValidationError, json.JSONDecodeError, RuntimeError)):
            logger.error(traceback.format_exc())
        return _make_result(
            status="failed",
            stage_1_output=stage1_dict,
            stage_2_output=stage2_dict,
            stage_3_output=stage3_dict,
            report=_generate_failure_report(
                stage=4, stage_name="Ad Creative Generation",
                reason=reason, raw_output=raw_stage4,
                stage1=stage1_validated, stage2=stage2_validated, stage3=stage3_validated,
                per_stage_usage=per_stage_usage, total_usage=total_usage,
            ),
            error={"stage": 4, "reason": str(e)},
            token_usage={"per_stage": per_stage_usage, "total": total_usage},
        )

    stage4_dict = stage4_validated.model_dump()

    # ------------------------------------------------------------------
    # All stages complete — build final report
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("=== ALL STAGES COMPLETE ===")
    logger.info(
        "Total tokens used: in=%d, out=%d, total=%d",
        total_usage["input_tokens"], total_usage["output_tokens"], total_usage["total_tokens"],
    )
    logger.info("=" * 60)

    report = _generate_full_report(
        stage1=stage1_validated,
        stage2=stage2_validated,
        stage3=stage3_validated,
        stage4=stage4_validated,
        per_stage_usage=per_stage_usage,
        total_usage=total_usage,
    )

    return _make_result(
        status="success",
        stage_1_output=stage1_dict,
        stage_2_output=stage2_dict,
        stage_3_output=stage3_dict,
        stage_4_output=stage4_dict,
        report=report,
        token_usage={"per_stage": per_stage_usage, "total": total_usage},
    )
