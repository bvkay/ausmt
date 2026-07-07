"""Shared access to the vendored, self-contained test fixture so science unit tests do NOT depend on
a sibling ausmt-surveys checkout. Cross-repo integration is a separate, explicit concern."""
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXAMPLE_SURVEY = FIXTURES / "example-survey"


def example_edis():
    return sorted((EXAMPLE_SURVEY / "transfer_functions" / "edi").glob("*.edi"))
