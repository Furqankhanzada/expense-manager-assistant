"""Pytest configuration and fixtures."""

import pytest
from decimal import Decimal
from datetime import date


@pytest.fixture
def sample_expense_text():
    """Sample expense text messages for testing."""
    return [
        ("Spent $25 on lunch", Decimal("25.00"), "USD", "lunch"),
        ("Uber ride 15 dollars", Decimal("15.00"), "USD", "Uber ride"),
        ("paid 50 euros for groceries", Decimal("50.00"), "EUR", "groceries"),
        ("Coffee $4.50", Decimal("4.50"), "USD", "Coffee"),
    ]


@pytest.fixture
def sample_categories():
    """Sample category names."""
    return [
        "Food & Dining",
        "Transportation",
        "Shopping",
        "Entertainment",
        "Bills & Utilities",
        "Health",
        "Travel",
        "Education",
        "Groceries",
        "Other",
    ]
