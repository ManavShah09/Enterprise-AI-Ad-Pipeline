"""
Cosmos DB Foundation Data Service.

Connects to Azure Cosmos DB via the Gremlin API (read-only) to fetch
the live Relay Marketing Foundation entities. Results are cached with
a configurable TTL to avoid excessive queries.

Per the Problem Statement:
- Read-only access only. No mutations.
- Hardcoded entity lists are NOT allowed — all data comes from the graph.
- Cache TTL must be configurable.
"""

import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from gremlin_python.driver import client as gremlin_client, serializer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------------------------

_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

COSMOS_DB_ENDPOINT: str = os.getenv("COSMOS_DB_ENDPOINT", "")
COSMOS_DB_KEY: str = os.getenv("COSMOS_DB_KEY", "")
COSMOS_DB_DATABASE: str = os.getenv("COSMOS_DB_DATABASE", "")
COSMOS_DB_GRAPH: str = os.getenv("COSMOS_DB_GRAPH", "")
CACHE_TTL_SECONDS: int = int(os.getenv("FOUNDATION_CACHE_TTL_SECONDS", "300"))

# All known vertex labels in the Relay Marketing Foundation graph
FOUNDATION_LABELS = [
    "MarketingFoundation",
    "MarketingAudience",
    "ProblemValue",
    "ICPModel",
    "ICPExperience",
    "Product",
    "ProductMessaging",
    "ProductUseCase",
    "ValueDriver",
    "Differentiator",
    "ProductFeature",
    "MarketingTrigger",
    "Competitor",
]


# ---------------------------------------------------------------------------
# Simple TTL cache
# ---------------------------------------------------------------------------

_cache: dict | None = None
_cache_timestamp: float = 0.0


def _is_cache_valid() -> bool:
    """Check if the cached data is still within the TTL window."""
    if _cache is None:
        return False
    return (time.time() - _cache_timestamp) < CACHE_TTL_SECONDS


def invalidate_cache():
    """Force-clear the foundation data cache."""
    global _cache, _cache_timestamp
    _cache = None
    _cache_timestamp = 0.0
    logger.info("Foundation data cache invalidated.")


# ---------------------------------------------------------------------------
# Gremlin client helpers
# ---------------------------------------------------------------------------

def _create_gremlin_client() -> gremlin_client.Client:
    """Create a Gremlin client connected to Cosmos DB."""
    if not all([COSMOS_DB_ENDPOINT, COSMOS_DB_KEY, COSMOS_DB_DATABASE, COSMOS_DB_GRAPH]):
        raise RuntimeError(
            "Cosmos DB configuration is incomplete. "
            "Please set COSMOS_DB_ENDPOINT, COSMOS_DB_KEY, COSMOS_DB_DATABASE, "
            "and COSMOS_DB_GRAPH in the .env file."
        )

    # Cosmos DB Gremlin requires username in format: /dbs/{db}/colls/{graph}
    username = f"/dbs/{COSMOS_DB_DATABASE}/colls/{COSMOS_DB_GRAPH}"

    logger.info(
        "Connecting to Cosmos DB Gremlin: %s (db=%s, graph=%s)",
        COSMOS_DB_ENDPOINT, COSMOS_DB_DATABASE, COSMOS_DB_GRAPH,
    )

    return gremlin_client.Client(
        url=COSMOS_DB_ENDPOINT,
        traversal_source="g",
        username=username,
        password=COSMOS_DB_KEY,
        message_serializer=serializer.GraphSONSerializersV2d0(),
    )


def _flatten_value_map(raw_vertex: dict) -> dict:
    """
    Flatten a Gremlin valueMap(true) result into a simple dict.

    Gremlin returns properties as lists, e.g. {"name": ["Relay Human Cloud"]}.
    This flattens single-element lists to their value.
    """
    flat = {}
    for key, value in raw_vertex.items():
        if isinstance(value, list) and len(value) == 1:
            flat[key] = value[0]
        elif isinstance(value, list) and len(value) > 1:
            flat[key] = value
        else:
            flat[key] = value
    return flat


def _fetch_vertices_by_label(
    client: gremlin_client.Client,
    label: str,
) -> list[dict]:
    """
    Fetch all vertices for a given label using a read-only Gremlin query.

    Uses: g.V().hasLabel('<label>').valueMap(true)
    """
    query = f"g.V().hasLabel('{label}').valueMap(true)"
    logger.debug("Executing Gremlin query: %s", query)

    try:
        result_set = client.submit(query)
        results = result_set.all().result()

        vertices = [_flatten_value_map(v) for v in results]
        logger.info("  %s: %d vertices fetched", label, len(vertices))
        return vertices

    except Exception as e:
        logger.warning("Failed to fetch label '%s': %s", label, e)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_foundation_data() -> dict:
    """
    Get the full Relay Marketing Foundation data from Cosmos DB.

    Returns a dict keyed by label name, each containing a list of
    vertex dicts with their properties.

    Results are cached for CACHE_TTL_SECONDS to minimize DB queries.

    Example return value:
    {
        "MarketingFoundation": [{"id": "...", "name": "Relay Human Cloud"}],
        "MarketingAudience": [{"id": "...", "name": "Staff Augmentation"}, ...],
        ...
    }
    """
    global _cache, _cache_timestamp

    # Return cached data if still valid
    if _is_cache_valid():
        logger.info("Using cached foundation data (age: %.0fs, TTL: %ds)",
                     time.time() - _cache_timestamp, CACHE_TTL_SECONDS)
        return _cache

    # Fetch fresh data from Cosmos DB
    logger.info("Fetching foundation data from Cosmos DB...")
    client = _create_gremlin_client()

    try:
        foundation = {}
        total_vertices = 0

        for label in FOUNDATION_LABELS:
            vertices = _fetch_vertices_by_label(client, label)
            foundation[label] = vertices
            total_vertices += len(vertices)

        logger.info(
            "Foundation data loaded: %d labels, %d total vertices",
            len(foundation), total_vertices,
        )

        # Update cache
        _cache = foundation
        _cache_timestamp = time.time()

        return foundation

    finally:
        client.close()
        logger.debug("Gremlin client closed.")


def get_foundation_summary(foundation_data: dict) -> str:
    """
    Create a human-readable summary of the foundation data
    for embedding in the Stage 2 agent's prompt.

    The format is designed to make it unambiguous for the LLM
    which actual entity NAMES to pick (not the category labels).
    """
    lines = [
        "# Relay Marketing Foundation — Available Entities",
        "",
        "Below are all entities from the live Relay Marketing Foundation database.",
        "When mapping the transcript, you MUST select actual entity NAMES from these lists.",
        "Do NOT use the category labels (like 'MarketingAudience') as values.",
        "",
    ]

    for label, vertices in foundation_data.items():
        if not vertices:
            lines.append(f"### {label}")
            lines.append("  (no entities)")
            lines.append("")
            continue

        lines.append(f"### {label}")

        # Extract all names for quick reference
        names = []
        for v in vertices:
            name = _extract_entity_name(v)
            names.append(name)

            # Show full details for each entity
            desc = (
                v.get("description") or v.get("Description")
                or v.get("desc") or v.get("Desc") or ""
            )
            if desc:
                lines.append(f"  - \"{name}\" — {desc}")
            else:
                # Show other properties if no description
                other_props = {
                    k: v_val for k, v_val in v.items()
                    if k not in ("id", "label", "name", "Name", "pk", "partition_key")
                    and v_val
                }
                if other_props:
                    props_str = ", ".join(f"{k}={v_val}" for k, v_val in other_props.items())
                    lines.append(f"  - \"{name}\" ({props_str})")
                else:
                    lines.append(f"  - \"{name}\"")

        lines.append(f"  **Available values:** {', '.join(names)}")
        lines.append("")

    # Log the raw data for debugging
    logger.debug("Foundation summary generated (%d lines)", len(lines))

    return "\n".join(lines)


def _extract_entity_name(vertex: dict) -> str:
    """Extract the most meaningful name from a vertex dict."""
    # Try common name fields in priority order
    for key in ("name", "Name", "title", "Title", "displayName", "DisplayName"):
        val = vertex.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
        # Handle case where value is still a list (not flattened)
        if val and isinstance(val, list):
            return str(val[0]).strip()

    # Fallback to the vertex label + id
    label = vertex.get("label", "")
    vid = vertex.get("id", "unknown")
    return f"{label}:{vid}" if label else str(vid)


def debug_dump_foundation(foundation_data: dict) -> str:
    """
    Dump raw foundation data as JSON for debugging.
    Useful to inspect what Cosmos DB is actually returning.
    """
    import json

    output = {}
    for label, vertices in foundation_data.items():
        output[label] = {
            "count": len(vertices),
            "vertices": vertices[:3],  # First 3 for brevity
        }
    return json.dumps(output, indent=2, default=str)

