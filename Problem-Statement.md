# Problem Statement: Relay AI Ad Pipeline

---

# Background / Context

Relay Human Cloud runs paid video and discovery-call style advertisements.

Today, creating a new on-brand advertisement requires a marketer to:

1. Study a competitor or reference advertisement.
2. Understand why the advertisement works.
3. Rewrite the advertisement using Relay's voice and messaging.

This process is:

- Slow
- Inconsistent
- Highly dependent on individual knowledge of:
  - Relay messaging
  - Relay products
  - Competitor positioning

## Goal

Automate this process using a multi-agent AI pipeline.

A user should be able to paste a reference advertisement transcript and receive:

1. A brand-new Relay advertisement script.
2. A detailed report explaining how the script was derived.

---

# Objective

Build and operate an API service that accepts a raw reference-ad transcript and processes it through four sequential AI agents.

## Expected Outputs

### 1. Structured Transcript

A structured version of the reference advertisement containing:

- Intro
- Numbered content blocks
- CTA (Call-to-Action)

### 2. Taxonomy Mapping

A tagged version mapped to:

- Relay's controlled taxonomy
- Real Relay entities

### 3. Ad Strategy Recipe

A reusable recipe that captures:

- Persuasion structure
- Strategic flow

The recipe must be abstracted from the original wording.

### 4. New Relay Advertisement

A brand-new Relay advertisement script generated from:

- The recipe
- Approved Relay content

## Final Deliverables

The system must produce:

1. A human-readable **Ad Pipeline Report** in Markdown format.
2. Raw JSON output from every stage.

---

# Pipeline Architecture

## End-to-End Flow

```text
Transcript
    │
    ▼
Orchestrator
    │
    ├─ Step 0: Resolve Inputs & Apply Relay Defaults
    │
    ▼
Stage 1: Transcript Structuring
    Output:
    - Intro
    - Numbered Content Blocks
    - CTA

    ▼
Stage 2: Taxonomy Tagging
    Output:
    - 22-Tag Taxonomy Classification
    - Relay Entity Mapping

    ▼
Stage 3: Ad Strategy
    Output:
    - Recipe
    - Signature
    - Persuasion Pattern
    - Arc

    ▼
Stage 4: Ad Creative
    Output:
    - New Relay Ad Script
    - Generated using Recipe + Relay Defaults

    ▼
Final Output:
Ad Pipeline Report (Markdown)
```

---

# Hard Rules for the Orchestrator

The orchestrator is responsible only for:

- Routing
- Validation
- Input resolution
- Final report generation

The orchestrator must **never**:

- Write advertisement copy
- Reclassify taxonomy tags

## Agent Responsibilities

All content generation and analysis must occur inside the four agents.

## Data Isolation Rules

### Stage 1 and Stage 2 Output

The textual content generated in:

- Stage 1
- Stage 2

must **never** be passed directly to Stage 4.

### Stage 3 Recipe

The recipe produced by Stage 3 must contain:

- Structure only
- No copied language
- No transcript wording

### Stage 4 Output

The final Relay advertisement must:

- Be original content
- Not be a paraphrase of the reference transcript

## Validation Rules

- Every stage must produce JSON conforming to a predefined contract.
- The first stage that fails validation must stop the pipeline.
- No downstream stages may execute after a failure.

## Failure Reporting

If any stage fails, the final report must clearly state:

- Which stage failed
- Why it failed

---

# Controlled Vocabularies

The Tagging and Strategy stages may only use values from the approved sets below.

Any value outside these sets must be rejected by the orchestrator.

---

# Primary Taxonomy Tags (22)

```text
audience
problem
value
product
product_messaging
feature
benefit
differentiator
use_case
value_driver
marketing_trigger
icp
icp_experience
competitor
brand_positioning
social_proof
objection_handling
process_descriptor
offer
call_to_action
urgency
uncategorized
```

---

# Persuasion Patterns (12)

```text
problem_solution
testimonial_driven
feature_led
benefit_led
urgency_led
comparison
storytelling
offer_led
objection_handling_led
process_led
brand_led
hybrid
```

---

# Review Flag Reasons (8)

```text
low_confidence
uncategorized_block
entity_not_in_foundation
ambiguous_tag
missing_cta_context
unclear_intro
non_relay_company
weak_entity_match
```

---

# Confidence Levels

```text
high
medium
low
```

---

# Grounding in the Live Relay Marketing Foundation

## Entity Mapping Requirements

Stage 2 (Taxonomy Tagging) must ground all entity mapping against the live Relay Marketing Foundation.

Hardcoded entity lists are not allowed.

## Source of Truth

Azure Cosmos DB using:

- Gremlin API
- Graph API

## Graph Contents

The graph contains entity types such as:

- MarketingAudience
- ProblemValue
- Product
- Competitor
- Other related Relay marketing entities

## Database Access Rules

The connection must be:

- Read-only

Allowed query pattern:

```gremlin
g.V()...valueMap()
```

The pipeline must:

- Read data only
- Never modify the graph

Mutation operations are prohibited.

---

# Caching Requirements

Live foundation data must be cached.

The cache TTL (Time-To-Live) must be configurable.

---

# Foundation Diff Endpoint

The system must expose a diff endpoint that reports:

- Exact differences between the live Cosmos DB graph
- The local Markdown snapshot

The report must clearly identify:

- Added entities
- Removed entities
- Modified entities