"""Pure analytics derived from the FinSight metric engine."""

from finsight.analytics.config import RiskThresholds, load_risk_thresholds
from finsight.analytics.benchmark import build_peer_benchmark
from finsight.analytics.insights import build_financial_insights
from finsight.analytics.models import RiskAssessment
from finsight.analytics.risk import analyze_financial_risk

__all__ = ["RiskAssessment", "RiskThresholds", "analyze_financial_risk", "build_financial_insights", "build_peer_benchmark", "load_risk_thresholds"]
