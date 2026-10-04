"""Agent Tester: statistical evaluation of HTTP agents.

Public API used by the controller and by anyone embedding the runner:

- ``run_job`` executes an ``EvalJob`` and returns ``RunResults``.
- ``invoke_once`` performs a single dry-run invocation of a contract.
- ``parse_cases`` parses JSON / JSONL / CSV dataset text with line-level errors.
"""

from agent_tester._version import __version__
from agent_tester.dataset import DatasetParseError, parse_cases
from agent_tester.engine import invoke_once, run_job
from agent_tester.models import (
    OUTCOME_CLASSES,
    AgentContract,
    AgentSpec,
    Case,
    CaseResult,
    DatasetRef,
    EvalJob,
    EvalOptions,
    RunResults,
)

__all__ = [
    "OUTCOME_CLASSES",
    "AgentContract",
    "AgentSpec",
    "Case",
    "CaseResult",
    "DatasetParseError",
    "DatasetRef",
    "EvalJob",
    "EvalOptions",
    "RunResults",
    "__version__",
    "invoke_once",
    "parse_cases",
    "run_job",
]
