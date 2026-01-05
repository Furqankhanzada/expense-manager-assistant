"""Expense report generation using LLM."""

import logging
from datetime import date
from decimal import Decimal
from typing import Sequence

from src.database.models import Expense
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

REPORT_PROMPT = """You are a financial assistant helping users understand their spending.

Analyze the following expense data and provide a concise, helpful report.

Period: {start_date} to {end_date}
Currency: {currency}
Total Expenses: {total}

Spending by Category:
{category_breakdown}

Recent Expenses (last 10):
{recent_expenses}

Please provide:
1. A brief summary of spending patterns
2. The top spending categories
3. Any notable observations (unusual spending, trends, etc.)
4. 1-2 actionable suggestions for budget management

Keep the response concise and friendly. Use bullet points where appropriate.
Format amounts with currency symbol."""


async def generate_expense_report(
    expenses: Sequence[Expense],
    category_totals: list[tuple[str, Decimal]],
    start_date: date,
    end_date: date,
    currency: str,
    llm: LLMProvider,
) -> str:
    """Generate an AI-powered expense report."""
    if not expenses:
        return (
            f"No expenses recorded from {start_date} to {end_date}.\n\n"
            "Start tracking your expenses by sending messages like:\n"
            "- \"Spent $25 on lunch\"\n"
            "- \"Uber ride $15\"\n"
            "- Or send a photo of a receipt!"
        )

    # Calculate total
    total = sum(exp.amount for exp in expenses)

    # Format category breakdown
    category_lines = []
    for cat_name, cat_total in category_totals:
        percentage = (cat_total / total * 100) if total > 0 else 0
        category_lines.append(f"- {cat_name}: {currency} {cat_total:.2f} ({percentage:.1f}%)")
    category_breakdown = "\n".join(category_lines) if category_lines else "No categorized expenses"

    # Format recent expenses
    recent = list(expenses)[:10]
    expense_lines = []
    for exp in recent:
        cat_name = exp.category.name if exp.category else "Uncategorized"
        expense_lines.append(
            f"- {exp.expense_date}: {currency} {exp.amount:.2f} - {exp.description} ({cat_name})"
        )
    recent_expenses = "\n".join(expense_lines)

    prompt = REPORT_PROMPT.format(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        currency=currency,
        total=f"{currency} {total:.2f}",
        category_breakdown=category_breakdown,
        recent_expenses=recent_expenses,
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        report = await llm.complete(messages, temperature=0.5, max_tokens=800)
        return report
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        # Fallback to basic report
        return _generate_basic_report(
            expenses, category_totals, start_date, end_date, currency, total
        )


def _generate_basic_report(
    expenses: Sequence[Expense],
    category_totals: list[tuple[str, Decimal]],
    start_date: date,
    end_date: date,
    currency: str,
    total: Decimal,
) -> str:
    """Generate a basic report without LLM."""
    lines = [
        f"<b>Expense Report</b>",
        f"Period: {start_date} to {end_date}",
        f"Total: {currency} {total:.2f}",
        "",
        "<b>By Category:</b>",
    ]

    for cat_name, cat_total in category_totals:
        percentage = (cat_total / total * 100) if total > 0 else 0
        lines.append(f"  {cat_name}: {currency} {cat_total:.2f} ({percentage:.1f}%)")

    lines.append("")
    lines.append(f"<b>Total Transactions:</b> {len(expenses)}")

    return "\n".join(lines)


BUDGET_ADVICE_PROMPT = """You are a helpful financial advisor. Based on the user's spending data, provide brief, personalized budget advice.

Monthly spending: {currency} {monthly_total}
Top categories this month:
{top_categories}

Previous month's spending: {currency} {prev_month_total}

Provide 2-3 short, actionable tips for managing their budget. Be encouraging and specific.
Keep the response under 150 words."""


async def generate_budget_advice(
    monthly_total: Decimal,
    prev_month_total: Decimal,
    top_categories: list[tuple[str, Decimal]],
    currency: str,
    llm: LLMProvider,
) -> str:
    """Generate personalized budget advice."""
    top_cat_lines = []
    for cat_name, cat_total in top_categories[:5]:
        top_cat_lines.append(f"- {cat_name}: {currency} {cat_total:.2f}")

    prompt = BUDGET_ADVICE_PROMPT.format(
        currency=currency,
        monthly_total=f"{monthly_total:.2f}",
        prev_month_total=f"{prev_month_total:.2f}",
        top_categories="\n".join(top_cat_lines) or "No expenses yet",
    )

    messages = [{"role": "user", "content": prompt}]

    try:
        advice = await llm.complete(messages, temperature=0.6, max_tokens=300)
        return advice
    except Exception as e:
        logger.error(f"Error generating budget advice: {e}")
        return "Keep tracking your expenses to get personalized budget advice!"
