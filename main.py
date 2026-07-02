"""
Relay AI Ad Pipeline — Entry Point.

Run this script to test the pipeline with a sample advertisement transcript.
Usage:
    python main.py
"""

import json
import logging
import sys

from src.orchestrator import run_pipeline

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)

# ---------------------------------------------------------------------------
# Sample transcript for testing
# ---------------------------------------------------------------------------

SAMPLE_TRANSCRIPT = """

MyOutDesk Ad Transcript - Nearshoring

Are you considering adding new talent to your team, or maybe you just need a team period? You might be looking into local hires or exploring overseas outsourcing, but there's a third option that's becoming very popular among forward-thinking leaders: nearshoring. Right now, more companies are turning to Latin America for their talent than ever before. And honestly, it makes sense. For one, you're working in the same US time zones. So when you need something, you don't have to wait overnight for a reply. You guys are collaborating in real time. Plus MyOutDesk Latin talent is bilingual, Highly educated and trained to work like a real extension of your team They're ready to step in and support your day-to-day functions.

Everything from marketing, operations, customer support. Here's the part that really matters to leaders: the numbers. You can save as much as 50 to 60% compared to hiring locally, and that's with no loss to your communication, your quality or productivity. That's just a MyOutDesk promise. I'm inviting you to a free consultation with the MyOutDesk team. We'll explain to you exactly how Latin talent can plug into your business and start saving you time so that you can start focusing on growing and scaling your business. Click that link below and schedule appointment.

""".strip()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Run the pipeline with the sample transcript and display results."""
    print("=" * 70)
    print("  RELAY AI AD PIPELINE — Full Pipeline (Stages 1–4)")
    print("=" * 70)
    print()

    # Run the pipeline
    result = run_pipeline(SAMPLE_TRANSCRIPT)

    # Display the JSON result
    print()
    print("-" * 70)
    print("  RAW JSON RESULT")
    print("-" * 70)
    print(json.dumps(result, indent=2, default=str))

    # Display the Markdown report
    print()
    print("-" * 70)
    print("  PIPELINE REPORT (Markdown)")
    print("-" * 70)
    print(result["report"])

    # Exit with appropriate code
    if result["status"] == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
