"""Expense categorization using LLM."""

import json
import logging
from typing import Sequence

from src.database.models import Category
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

CATEGORIZE_PROMPT = """You are an expense categorization assistant. Given an expense description, determine the most appropriate category.

Available categories:
{categories}

Expense description: {description}

Return ONLY a JSON object with:
- category: string - the exact name of the most appropriate category from the list above
- confidence: number - confidence score from 0.0 to 1.0

Example response: {{"category": "Food & Dining", "confidence": 0.95}}

Return ONLY the JSON object, no other text."""


async def categorize_expense(
    description: str,
    categories: Sequence[Category],
    llm: LLMProvider,
) -> tuple[Category | None, float]:
    """Categorize an expense based on its description.

    Returns: (category, confidence) tuple
    """
    if not categories:
        return None, 0.0

    # Build category list string
    category_list = "\n".join(f"- {cat.name}" for cat in categories)

    prompt = CATEGORIZE_PROMPT.format(
        categories=category_list,
        description=description,
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.complete(messages, temperature=0.1, max_tokens=100)

        # Clean up response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()

        data = json.loads(response)

        category_name = data.get("category", "")
        confidence = float(data.get("confidence", 0.0))

        # Find matching category
        for cat in categories:
            if cat.name.lower() == category_name.lower():
                return cat, confidence

        # Fallback to "Other" category if exists
        for cat in categories:
            if cat.name.lower() == "other":
                return cat, 0.5

        return None, 0.0

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse categorization response: {e}")
        return None, 0.0
    except Exception as e:
        logger.error(f"Error categorizing expense: {e}")
        return None, 0.0


BULK_CATEGORIZE_PROMPT = """You are an expense categorization assistant. Categorize multiple expenses at once.

Available categories:
{categories}

Expenses to categorize:
{expenses}

Return a JSON array where each item has:
- index: number - the expense index (0-based)
- category: string - the exact category name from the list
- confidence: number - confidence score from 0.0 to 1.0

Example: [{{"index": 0, "category": "Food & Dining", "confidence": 0.95}}, {{"index": 1, "category": "Transportation", "confidence": 0.88}}]

Return ONLY the JSON array, no other text."""


async def bulk_categorize(
    descriptions: list[str],
    categories: Sequence[Category],
    llm: LLMProvider,
) -> list[tuple[Category | None, float]]:
    """Categorize multiple expenses at once for efficiency.

    Returns: List of (category, confidence) tuples
    """
    if not categories or not descriptions:
        return [(None, 0.0)] * len(descriptions)

    category_list = "\n".join(f"- {cat.name}" for cat in categories)
    expense_list = "\n".join(f"{i}. {desc}" for i, desc in enumerate(descriptions))

    prompt = BULK_CATEGORIZE_PROMPT.format(
        categories=category_list,
        expenses=expense_list,
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.complete(messages, temperature=0.1, max_tokens=500)

        # Clean up response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()

        data = json.loads(response)

        # Build result list
        results: list[tuple[Category | None, float]] = [(None, 0.0)] * len(descriptions)

        category_map = {cat.name.lower(): cat for cat in categories}

        for item in data:
            idx = item.get("index", -1)
            if 0 <= idx < len(descriptions):
                cat_name = item.get("category", "").lower()
                confidence = float(item.get("confidence", 0.0))

                if cat_name in category_map:
                    results[idx] = (category_map[cat_name], confidence)

        return results

    except Exception as e:
        logger.error(f"Error in bulk categorization: {e}")
        return [(None, 0.0)] * len(descriptions)
