"""Expense categorization using LLM."""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Sequence

from src.database.models import Category
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


class QueryType(Enum):
    """Types of expense queries."""
    ITEM_PRICE = "item_price"  # "how much was milk?"
    CATEGORY_SPENDING = "category_spending"  # "how much on petrol last month?"
    DATE_SPENDING = "date_spending"  # "how much yesterday?"
    LIST_EXPENSES = "list_expenses"  # "list today's expenses", "show my expenses"
    NOT_A_QUERY = "not_a_query"


@dataclass
class ParsedQuery:
    """Parsed query information."""
    query_type: QueryType
    item_name: str | None = None  # For item price queries
    category_hint: str | None = None  # For category spending queries
    start_date: date | None = None  # For date range queries
    end_date: date | None = None  # For date range queries
    is_valid: bool = False


QUERY_PARSE_PROMPT = """You are an expense tracking assistant. Analyze if the user's message is a query about their expenses.

Today's date is {today}.

User message: "{message}"

Determine if this is a query and what type:
1. ITEM_PRICE - asking about the price of a specific item (e.g., "how much was milk?", "what did I pay for eggs last time?")
2. CATEGORY_SPENDING - asking about spending in a category (e.g., "how much on petrol last month?", "what did I spend on transportation?")
3. DATE_SPENDING - asking about total/summary spending on a date/period (e.g., "how much yesterday?", "what did I spend last week?", "total spending today?")
4. LIST_EXPENSES - asking to see detailed list of expenses (e.g., "list today's expenses", "show my expenses", "what did I buy today?", "show details of yesterday's expenses")
5. NOT_A_QUERY - not a query (e.g., new expense, correction, general chat)

KEY DIFFERENCE between DATE_SPENDING and LIST_EXPENSES:
- DATE_SPENDING: wants summary/total (e.g., "how much", "total", "what did I spend")
- LIST_EXPENSES: wants detailed list (e.g., "list", "show", "what did I buy", "details")

Return ONLY a JSON object:
{{
  "query_type": "ITEM_PRICE" | "CATEGORY_SPENDING" | "DATE_SPENDING" | "LIST_EXPENSES" | "NOT_A_QUERY",
  "item_name": "item name if ITEM_PRICE query" or null,
  "category_hint": "category keyword if CATEGORY_SPENDING or LIST_EXPENSES query" or null,
  "start_date": "YYYY-MM-DD start date" or null,
  "end_date": "YYYY-MM-DD end date" or null
}}

Examples:
- "how much was milk?" → {{"query_type": "ITEM_PRICE", "item_name": "milk", "category_hint": null, "start_date": null, "end_date": null}}
- "how much did I spend on petrol last month?" → {{"query_type": "CATEGORY_SPENDING", "item_name": null, "category_hint": "petrol", "start_date": "{last_month_start}", "end_date": "{last_month_end}"}}
- "how much yesterday?" → {{"query_type": "DATE_SPENDING", "item_name": null, "category_hint": null, "start_date": "{yesterday}", "end_date": "{yesterday}"}}
- "how much this week?" → {{"query_type": "DATE_SPENDING", "item_name": null, "category_hint": null, "start_date": "{week_start}", "end_date": "{today}"}}
- "list today's expenses" → {{"query_type": "LIST_EXPENSES", "item_name": null, "category_hint": null, "start_date": "{today}", "end_date": "{today}"}}
- "show my expenses yesterday" → {{"query_type": "LIST_EXPENSES", "item_name": null, "category_hint": null, "start_date": "{yesterday}", "end_date": "{yesterday}"}}
- "what did I buy this week?" → {{"query_type": "LIST_EXPENSES", "item_name": null, "category_hint": null, "start_date": "{week_start}", "end_date": "{today}"}}
- "spent $50 on lunch" → {{"query_type": "NOT_A_QUERY", "item_name": null, "category_hint": null, "start_date": null, "end_date": null}}

Return ONLY the JSON object, no other text."""


async def parse_query(
    message: str,
    llm: LLMProvider,
) -> ParsedQuery:
    """Parse a message to see if it's a spending query.

    Returns: ParsedQuery with query details
    """
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Calculate last month dates
    if today.month == 1:
        last_month_start = date(today.year - 1, 12, 1)
        last_month_end = date(today.year - 1, 12, 31)
    else:
        last_month_start = date(today.year, today.month - 1, 1)
        # Last day of last month
        last_month_end = date(today.year, today.month, 1) - timedelta(days=1)

    # Week start (Monday)
    week_start = today - timedelta(days=today.weekday())

    prompt = QUERY_PARSE_PROMPT.format(
        today=today.isoformat(),
        yesterday=yesterday.isoformat(),
        last_month_start=last_month_start.isoformat(),
        last_month_end=last_month_end.isoformat(),
        week_start=week_start.isoformat(),
        message=message,
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.complete(messages, temperature=0.1, max_tokens=300)

        # Clean up response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()

        data = json.loads(response)

        query_type_str = data.get("query_type", "NOT_A_QUERY")
        try:
            query_type = QueryType(query_type_str.lower())
        except ValueError:
            query_type = QueryType.NOT_A_QUERY

        if query_type == QueryType.NOT_A_QUERY:
            return ParsedQuery(query_type=QueryType.NOT_A_QUERY)

        # Parse dates
        start_date = None
        end_date = None
        if data.get("start_date"):
            try:
                start_date = datetime.strptime(data["start_date"], "%Y-%m-%d").date()
            except ValueError:
                pass
        if data.get("end_date"):
            try:
                end_date = datetime.strptime(data["end_date"], "%Y-%m-%d").date()
            except ValueError:
                pass

        return ParsedQuery(
            query_type=query_type,
            item_name=data.get("item_name"),
            category_hint=data.get("category_hint"),
            start_date=start_date,
            end_date=end_date,
            is_valid=True,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse query response: {e}")
        return ParsedQuery(query_type=QueryType.NOT_A_QUERY)
    except Exception as e:
        logger.error(f"Error parsing query: {e}")
        return ParsedQuery(query_type=QueryType.NOT_A_QUERY)


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
