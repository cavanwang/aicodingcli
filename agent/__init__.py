# Auto-generated fallback for optional dependency: pandas
try:
    import pandas as pandas
except ImportError:  # pragma: no cover - optional dependency fallback
    pandas = None

from agent.core import Agent, create_agent

__all__ = ["create_agent"]
