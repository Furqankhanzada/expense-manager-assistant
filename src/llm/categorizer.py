"""Expense categorization using LLM."""

import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from src.database.models import Category
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class ExpenseCorrection:
    """Represents a correction to an expense."""
    is_correction: bool = False
    new_category: str | None = None
    new_description: str | None = None
    new_amount: Decimal | None = None
    message: str | None = None  # Any message to show to user


CORRECTION_PROMPT = """You are an expense tracking assistant. The user just added an expense and is now sending a follow-up message.

Last expense added:
- Amount: {amount} {currency}
- Description: {description}
- Category: {category}

User's follow-up message: "{message}"

Determine if this is a correction/clarification about the expense. The user might be:
1. Correcting the category (e.g., "that was for petrol", "it's transportation", "wrong category, should be fuel")
2. Clarifying the description (e.g., "it was from Shell station", "for my car")
3. Correcting the amount (e.g., "actually it was 500", "the amount is wrong, it's 1500")
4. Just chatting (not related to the expense)

Available categories for this user:
{categories}

Return ONLY a JSON object:
{{
  "is_correction": true/false,
  "correction_type": "category" | "description" | "amount" | "none",
  "new_category": "exact category name from list" or null,
  "new_description": "updated description" or null,
  "new_amount": number or null
}}

Examples:
- "that was for petrol" -> {{"is_correction": true, "correction_type": "category", "new_category": "Transportation", "new_description": "Petrol", "new_amount": null}}
- "it's from Shell" -> {{"is_correction": true, "correction_type": "description", "new_category": null, "new_description": "Petrol from Shell", "new_amount": null}}
- "actually it was 200" -> {{"is_correction": true, "correction_type": "amount", "new_category": null, "new_description": null, "new_amount": 200}}
- "thanks" -> {{"is_correction": false, "correction_type": "none", "new_category": null, "new_description": null, "new_amount": null}}

Return ONLY the JSON object, no other text."""


async def understand_correction(
    message: str,
    last_expense_amount: Decimal,
    last_expense_currency: str,
    last_expense_description: str,
    last_expense_category: str,
    categories: Sequence[Category],
    llm: LLMProvider,
) -> ExpenseCorrection:
    """Understand if a message is a correction to the last expense.

    Returns: ExpenseCorrection with details about what to update
    """
    category_list = "\n".join(f"- {cat.name}" for cat in categories)

    prompt = CORRECTION_PROMPT.format(
        amount=last_expense_amount,
        currency=last_expense_currency,
        description=last_expense_description,
        category=last_expense_category,
        message=message,
        categories=category_list,
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.complete(messages, temperature=0.1, max_tokens=200)

        # Clean up response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()

        data = json.loads(response)

        correction = ExpenseCorrection(
            is_correction=data.get("is_correction", False),
        )

        if correction.is_correction:
            if data.get("new_category"):
                # Validate category exists
                for cat in categories:
                    if cat.name.lower() == data["new_category"].lower():
                        correction.new_category = cat.name
                        break

            if data.get("new_description"):
                correction.new_description = data["new_description"]

            if data.get("new_amount") is not None:
                try:
                    correction.new_amount = Decimal(str(data["new_amount"]))
                except:
                    pass

        return correction

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse correction response: {e}")
        return ExpenseCorrection()
    except Exception as e:
        logger.error(f"Error understanding correction: {e}")
        return ExpenseCorrection()

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
