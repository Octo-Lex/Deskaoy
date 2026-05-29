"""Orchestration — multi-app desktop workflows with DAG execution."""

from deskaoy.orchestration.app_agent import AppAgent, AppAgentConfig, AppAgentResult
from deskaoy.orchestration.blackboard import Blackboard
from deskaoy.orchestration.dag import DAGExecutor, DAGNode, DAGNodeResult
from deskaoy.orchestration.host_agent import HostAgent, OrchestratedResult
from deskaoy.orchestration.templates import TEMPLATES, match_template

__all__ = [
    "Blackboard",
    "DAGExecutor",
    "DAGNode",
    "DAGNodeResult",
    "AppAgent",
    "AppAgentConfig",
    "AppAgentResult",
    "HostAgent",
    "OrchestratedResult",
    "TEMPLATES",
    "match_template",
]
