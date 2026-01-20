"""AI-powered HVAC analyzer and optimizer using LLM."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .bulk_reader import HVACSystemState

logger = logging.getLogger("hvac_ai_analyzer")

# Optional AI packages
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


@dataclass
class AIRecommendation:
    """AI recommendation for HVAC adjustment."""

    action: str  # "force" or "unforce"
    point: str
    value: Optional[str] = None
    reason: str = ""
    confidence: float = 0.5
    priority: int = 5  # 1-10, higher = more important


class HVACAIAnalyzer:
    """Analyzes HVAC system state using LLM and provides recommendations."""

    def __init__(self, ai_backend: str = "openai",
                 api_key: Optional[str] = None) -> None:
        """Initialize AI analyzer."""
        self.ai_backend = ai_backend
        self.api_key = api_key
        self.client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize LLM client based on backend."""
        if self.ai_backend == "openai":
            if not OPENAI_AVAILABLE:
                logger.warning("OpenAI package not installed. Install with: pip install openai")
                self.client = None
            elif not self.api_key:
                logger.warning("OpenAI API key not configured. Using rule-based analysis.")
                self.client = None
            else:
                self.client = OpenAI(api_key=self.api_key)
        elif self.ai_backend == "anthropic":
            if not ANTHROPIC_AVAILABLE:
                logger.warning("Anthropic package not installed. Install with: pip install anthropic")
                self.client = None
            elif not self.api_key:
                logger.warning("Anthropic API key not configured. Using rule-based analysis.")
                self.client = None
            else:
                self.client = Anthropic(api_key=self.api_key)
        else:
            self.client = None

    def analyze_system_state(
        self, state: HVACSystemState
    ) -> tuple[str, list[AIRecommendation]]:
        """Analyze HVAC system state and provide recommendations."""
        if self.client is None:
            return self._analyze_without_ai(state)

        summary = self._create_system_summary(state)
        analysis = self._get_ai_analysis(summary)
        recommendations = self._parse_recommendations(analysis, state)

        return analysis, recommendations

    def _create_system_summary(self, state: HVACSystemState) -> str:
        """Create detailed system summary for AI analysis."""
        lines = [
            "Current HVAC System State:",
            f"Timestamp: {state.timestamp}",
            "",
        ]

        if state.temperature_avg is not None:
            lines.append(
                f"Average Temperature: {state.temperature_avg:.1f}°C"
            )
        if state.humidity_avg is not None:
            lines.append(f"Average Humidity: {state.humidity_avg:.1f}%")

        lines.append("\nPoint Values:")
        for point_name, point in state.points.items():
            if point.success:
                lines.append(
                    f"- {point.name}: {point.value} {point.unit or ''}"
                )

        lines.append(
            "\nBased on this HVAC system state, provide recommendations "
            "for optimization. Focus on:"
        )
        lines.append("1. Energy efficiency")
        lines.append("2. Comfort levels")
        lines.append("3. System balance")
        lines.append(
            "\nFor each recommendation, specify the action (force/unforce), "
            "the point name, value if forcing, confidence level (0-1), "
            "and priority (1-10)."
        )

        return "\n".join(lines)

    def _get_ai_analysis(self, summary: str) -> str:
        """Get analysis from AI model."""
        if self.ai_backend == "openai" and self.client:
            try:
                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an HVAC system optimization expert. "
                                "Analyze HVAC system states and provide "
                                "actionable recommendations for optimal "
                                "operation."
                            ),
                        },
                        {"role": "user", "content": summary},
                    ],
                    temperature=0.7,
                    max_tokens=1000,
                )
                return response.choices[0].message.content
            except Exception as exc:
                return f"AI Analysis Error: {str(exc)}"

        elif self.ai_backend == "anthropic" and self.client:
            try:
                response = self.client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=1000,
                    messages=[
                        {
                            "role": "user",
                            "content": summary,
                        }
                    ],
                    system=(
                        "You are an HVAC system optimization expert. "
                        "Analyze HVAC system states and provide actionable "
                        "recommendations."
                    ),
                )
                return response.content[0].text
            except Exception as exc:
                return f"AI Analysis Error: {str(exc)}"

        return "No AI backend configured"

    def _analyze_without_ai(
        self, state: HVACSystemState
    ) -> tuple[str, list[AIRecommendation]]:
        """Fallback analysis without AI."""
        analysis = "System Analysis (No AI):\n"
        analysis += f"Timestamp: {state.timestamp}\n"

        if state.temperature_avg is not None:
            analysis += f"Average Temperature: {state.temperature_avg:.1f}°C\n"
            if state.temperature_avg > 22:
                analysis += (
                    "  → Temperature is above target. "
                    "Consider increasing cooling.\n"
                )
            elif state.temperature_avg < 20:
                analysis += (
                    "  → Temperature is below target. "
                    "Consider increasing heating.\n"
                )

        if state.humidity_avg is not None:
            analysis += f"Average Humidity: {state.humidity_avg:.1f}%\n"
            if state.humidity_avg > 60:
                analysis += (
                    "  → Humidity is high. "
                    "Consider increasing dehumidification.\n"
                )
            elif state.humidity_avg < 30:
                analysis += (
                    "  → Humidity is low. "
                    "Consider reducing dehumidification.\n"
                )

        recommendations = self._generate_basic_recommendations(state)
        return analysis, recommendations

    def _generate_basic_recommendations(
        self, state: HVACSystemState
    ) -> list[AIRecommendation]:
        """Generate basic recommendations without AI."""
        recommendations = []

        if state.temperature_avg and state.temperature_avg > 23:
            recommendations.append(
                AIRecommendation(
                    action="force",
                    point="360.005-JP40_Pos",
                    value="50",
                    reason="Temperature above target, increase cooling",
                    confidence=0.7,
                    priority=7,
                )
            )

        if state.humidity_avg and state.humidity_avg > 65:
            recommendations.append(
                AIRecommendation(
                    action="force",
                    point="360.005-JV40_Pos",
                    value="75",
                    reason="High humidity detected, increase ventilation",
                    confidence=0.6,
                    priority=6,
                )
            )

        return recommendations

    def _parse_recommendations(
        self, analysis: str, state: HVACSystemState
    ) -> list[AIRecommendation]:
        """Parse AI response to extract recommendations."""
        # In a production system, this would use more sophisticated parsing
        recommendations = []

        # Simple extraction based on keywords
        if "increase cooling" in analysis.lower():
            recommendations.append(
                AIRecommendation(
                    action="force",
                    point="360.005-JP40_Pos",
                    value="50",
                    reason="AI recommends cooling increase",
                    confidence=0.7,
                    priority=7,
                )
            )

        if "increase heating" in analysis.lower():
            recommendations.append(
                AIRecommendation(
                    action="force",
                    point="360.005-JV50_Pos",
                    value="50",
                    reason="AI recommends heating increase",
                    confidence=0.7,
                    priority=7,
                )
            )

        if "increase ventilation" in analysis.lower():
            recommendations.append(
                AIRecommendation(
                    action="force",
                    point="360.005-JV40_Pos",
                    value="75",
                    reason="AI recommends ventilation increase",
                    confidence=0.6,
                    priority=6,
                )
            )

        return recommendations

    def save_analysis_history(
        self, state: HVACSystemState, analysis: str,
        recommendations: list[AIRecommendation]
    ) -> None:
        """Save analysis history for learning."""
        history_dir = Path("data") / "analysis_history"
        history_dir.mkdir(parents=True, exist_ok=True)

        filename = state.timestamp.replace(":", "-").replace(".", "-")
        filepath = history_dir / f"analysis_{filename}.json"

        data = {
            "timestamp": state.timestamp,
            "analysis": analysis,
            "recommendations": [
                {
                    "action": r.action,
                    "point": r.point,
                    "value": r.value,
                    "reason": r.reason,
                    "confidence": r.confidence,
                    "priority": r.priority,
                }
                for r in recommendations
            ],
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
