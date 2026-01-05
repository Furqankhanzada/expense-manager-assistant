"""Expense parsing using LLM."""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

EXPENSE_PARSE_PROMPT = """You are an expense parsing assistant. Extract expense information from the user's message.

Return a JSON object with the following fields:
- amount: number (required) - the expense amount as a decimal number
- currency: string (optional) - three-letter currency code like USD, EUR, GBP. Default to USD if not specified
- description: string (required) - brief description of the expense
- category: string (optional) - suggest a category from: Food & Dining, Transportation, Shopping, Entertainment, Bills & Utilities, Health, Travel, Education, Groceries, Other
- date: string (optional) - the expense date in YYYY-MM-DD format. Use relative terms: "today", "yesterday", "last week" should be converted to actual dates. Today is {today}

If the message doesn't contain expense information, return: {{"error": "No expense found"}}

Examples:
Input: "Spent $45 on dinner last night"
Output: {{"amount": 45.00, "currency": "USD", "description": "Dinner", "category": "Food & Dining", "date": "{yesterday}"}}

Input: "Just paid 200 euros for flight tickets"
Output: {{"amount": 200.00, "currency": "EUR", "description": "Flight tickets", "category": "Travel", "date": "{today}"}}

Input: "Uber ride $15"
Output: {{"amount": 15.00, "currency": "USD", "description": "Uber ride", "category": "Transportation", "date": "{today}"}}

Input: "bought groceries 89.50"
Output: {{"amount": 89.50, "currency": "USD", "description": "Groceries", "category": "Groceries", "date": "{today}"}}

Now parse this message:
{message}

Return ONLY the JSON object, no other text."""


@dataclass
class ParsedExpense:
    """Parsed expense data."""

    amount: Decimal
    currency: str
    description: str
    category: str | None
    expense_date: date
    raw_input: str


async def parse_expense(
    text: str,
    llm: LLMProvider,
) -> ParsedExpense | None:
    """Parse expense information from text using LLM."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    prompt = EXPENSE_PARSE_PROMPT.format(
        today=today.isoformat(),
        yesterday=yesterday.isoformat(),
        message=text,
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        response = await llm.complete(messages, temperature=0.1, max_tokens=500)

        # Clean up response - remove markdown code blocks if present
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()

        data = json.loads(response)

        if "error" in data:
            logger.info(f"No expense found in message: {text}")
            return None

        # Parse the date
        expense_date = today
        if "date" in data and data["date"]:
            try:
                expense_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                pass

        return ParsedExpense(
            amount=Decimal(str(data["amount"])),
            currency=data.get("currency", "USD").upper(),
            description=data.get("description", ""),
            category=data.get("category"),
            expense_date=expense_date,
            raw_input=text,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing expense: {e}")
        return None


RECEIPT_PARSE_PROMPT = """You are a receipt parsing assistant. Analyze this receipt image and extract expense information.

Return a JSON object with:
- expenses: array of expense objects, each with:
  - amount: number (required) - the item/total amount
  - currency: string - currency code (USD, EUR, etc.)
  - description: string - item description or "Total" for receipt total
  - category: string - suggest from: Food & Dining, Transportation, Shopping, Entertainment, Bills & Utilities, Health, Travel, Education, Groceries, Other
- store_name: string (optional) - name of the store/merchant
- date: string (optional) - receipt date in YYYY-MM-DD format
- total: number (optional) - total amount on receipt

If the image is not a receipt or no expenses can be extracted, return: {{"error": "Could not parse receipt"}}

Return ONLY the JSON object, no other text."""


@dataclass
class ParsedReceipt:
    """Parsed receipt data."""

    expenses: list[ParsedExpense]
    store_name: str | None
    total: Decimal | None


async def parse_receipt_image(
    image_data: bytes,
    llm: LLMProvider,
    image_type: str = "image/jpeg",
) -> ParsedReceipt | None:
    """Parse expense information from a receipt image."""
    today = date.today()

    try:
        response = await llm.complete_with_image(
            prompt=RECEIPT_PARSE_PROMPT,
            image_data=image_data,
            image_type=image_type,
            temperature=0.1,
            max_tokens=1000,
        )

        # Clean up response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()

        data = json.loads(response)

        if "error" in data:
            logger.info("Could not parse receipt from image")
            return None

        # Parse receipt date
        receipt_date = today
        if "date" in data and data["date"]:
            try:
                receipt_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
            except ValueError:
                pass

        # Parse expenses
        expenses = []
        for exp in data.get("expenses", []):
            expenses.append(
                ParsedExpense(
                    amount=Decimal(str(exp["amount"])),
                    currency=exp.get("currency", "USD").upper(),
                    description=exp.get("description", ""),
                    category=exp.get("category"),
                    expense_date=receipt_date,
                    raw_input="[Receipt image]",
                )
            )

        return ParsedReceipt(
            expenses=expenses,
            store_name=data.get("store_name"),
            total=Decimal(str(data["total"])) if data.get("total") else None,
        )

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse receipt response as JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Error parsing receipt: {e}")
        return None
