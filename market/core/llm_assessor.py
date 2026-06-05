"""
llm_assessor.py — Claude-powered extracurricular strength rating.

Given a school, application round, and free-text extracurriculars, asks
Claude to rate the profile on a 1–10 scale relative to that school's
typical applicant pool.  Returns a (score, summary) tuple.

The score is used to adjust the XGBoost opening probability:
    adjustment = (score - 5.5) / 4.5 * 0.10
    final_prob  = clamp(ml_prob + adjustment, 0.01, 0.99)

If the API key is absent or the call fails, returns (5.5, None) so the
market opens at the pure XGBoost estimate with no qualitative bias.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are an expert college admissions consultant evaluating applicants.

School: {school}
Application round: {round}
Extracurriculars and achievements:
{extracurriculars}

Rate the strength of this applicant's extracurricular profile relative to a typical \
applicant to {school} on a scale of 1–10:
  1–3  weak  — minimal activities or achievements compared to this school's typical applicant
  4–6  average — activities that are common among applicants to this school
  7–9  strong — notable leadership, awards, or depth that stands out
  10   exceptional — nationally/internationally recognised achievements

Respond with valid JSON only (no markdown fences):
{{"score": <integer 1-10>, "summary": "<one or two sentences summarising the profile's strengths and weaknesses>"}}"""


async def assess_extracurriculars(
    school: str,
    round_: str,
    extracurriculars: str,
) -> tuple[Optional[float], Optional[str]]:
    """
    Returns (score, summary) or (None, None) if assessment is unavailable.
    score is 1–10; summary is a short string or None.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or not extracurriculars.strip():
        return None, None

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[
                {
                    "role": "user",
                    "content": _PROMPT_TEMPLATE.format(
                        school=school,
                        round=round_,
                        extracurriculars=extracurriculars.strip(),
                    ),
                }
            ],
        )
        raw = message.content[0].text.strip()
        data = json.loads(raw)
        score   = float(max(1, min(10, data["score"])))
        summary = str(data.get("summary", ""))[:512] or None
        return score, summary
    except Exception as exc:
        logger.warning("LLM assessor failed: %s", exc)
        return None, None


def blend_probability(ml_prob: float, llm_score: float) -> float:
    """
    Adjust the XGBoost probability by the LLM's extracurricular rating.
    A score of 5.5 is neutral (no change); 10 adds up to +10%, 1 subtracts up to -10%.
    """
    adjustment = (llm_score - 5.5) / 4.5 * 0.10
    return float(max(0.01, min(0.99, ml_prob + adjustment)))
