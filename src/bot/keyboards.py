"""Inline keyboards for bot interactions."""

from typing import Sequence
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.database.models import Category


def expense_confirmation_keyboard(expense_id: UUID) -> InlineKeyboardMarkup:
    """Create keyboard for expense confirmation/actions."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Edit",
                    callback_data=f"expense:edit:{expense_id}",
                ),
                InlineKeyboardButton(
                    text="Delete",
                    callback_data=f"expense:delete:{expense_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Change Category",
                    callback_data=f"expense:category:{expense_id}",
                ),
            ],
        ]
    )


def receipt_confirmation_keyboard(confirm_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for receipt confirmation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Confirm All",
                    callback_data=f"receipt:confirm:{confirm_id}",
                ),
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data=f"receipt:cancel:{confirm_id}",
                ),
            ],
        ]
    )


def category_selection_keyboard(
    categories: Sequence[Category],
    expense_id: UUID,
) -> InlineKeyboardMarkup:
    """Create keyboard for category selection."""
    buttons = []
    row = []

    for cat in categories:
        btn = InlineKeyboardButton(
            text=f"{cat.icon} {cat.name}" if cat.icon else cat.name,
            callback_data=f"setcat:{expense_id}:{cat.id}",
        )
        row.append(btn)

        # 2 buttons per row
        if len(row) == 2:
            buttons.append(row)
            row = []

    # Add remaining buttons
    if row:
        buttons.append(row)

    # Add cancel button
    buttons.append([
        InlineKeyboardButton(
            text="Cancel",
            callback_data=f"setcat:{expense_id}:cancel",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def delete_confirmation_keyboard(expense_id: UUID) -> InlineKeyboardMarkup:
    """Create keyboard for delete confirmation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Yes, Delete",
                    callback_data=f"delete:confirm:{expense_id}",
                ),
                InlineKeyboardButton(
                    text="No, Keep",
                    callback_data=f"delete:cancel:{expense_id}",
                ),
            ],
        ]
    )


def report_period_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for selecting report period."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="This Week",
                    callback_data="report:week",
                ),
                InlineKeyboardButton(
                    text="This Month",
                    callback_data="report:month",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Last 30 Days",
                    callback_data="report:30days",
                ),
                InlineKeyboardButton(
                    text="This Year",
                    callback_data="report:year",
                ),
            ],
        ]
    )


def settings_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for settings menu."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Change LLM Provider",
                    callback_data="settings:llm",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Change Currency",
                    callback_data="settings:currency",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Manage Categories",
                    callback_data="settings:categories",
                ),
            ],
        ]
    )


def llm_provider_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for LLM provider selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="OpenAI (GPT-4)",
                    callback_data="llm:openai",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Google Gemini",
                    callback_data="llm:gemini",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Grok (xAI)",
                    callback_data="llm:grok",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Ollama (Local)",
                    callback_data="llm:ollama",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Back",
                    callback_data="settings:back",
                ),
            ],
        ]
    )


def currency_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for currency selection."""
    currencies = [
        ("USD", "$"),
        ("EUR", "€"),
        ("GBP", "£"),
        ("JPY", "¥"),
        ("CAD", "C$"),
        ("AUD", "A$"),
        ("INR", "₹"),
        ("PKR", "Rs"),
    ]

    buttons = []
    row = []

    for code, symbol in currencies:
        btn = InlineKeyboardButton(
            text=f"{symbol} {code}",
            callback_data=f"currency:{code}",
        )
        row.append(btn)

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append([
        InlineKeyboardButton(
            text="Back",
            callback_data="settings:back",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def export_format_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for export format selection."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="CSV",
                    callback_data="export:csv",
                ),
                InlineKeyboardButton(
                    text="JSON",
                    callback_data="export:json",
                ),
            ],
        ]
    )


def setup_currency_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard for initial currency setup."""
    currencies = [
        ("USD", "$ USD"),
        ("EUR", "€ EUR"),
        ("GBP", "£ GBP"),
        ("JPY", "¥ JPY"),
        ("CAD", "C$ CAD"),
        ("AUD", "A$ AUD"),
        ("INR", "₹ INR"),
        ("PKR", "Rs PKR"),
        ("AED", "د.إ AED"),
        ("SAR", "﷼ SAR"),
    ]

    buttons = []
    row = []

    for code, label in currencies:
        btn = InlineKeyboardButton(
            text=label,
            callback_data=f"setup:currency:{code}",
        )
        row.append(btn)

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def family_menu_keyboard(has_household: bool, is_owner: bool = False) -> InlineKeyboardMarkup:
    """Create keyboard for family/household menu."""
    buttons = []

    if has_household:
        buttons.append([
            InlineKeyboardButton(
                text="View Members",
                callback_data="family:members",
            ),
        ])
        if is_owner:
            buttons.append([
                InlineKeyboardButton(
                    text="Show Invite Code",
                    callback_data="family:invite",
                ),
            ])
            buttons.append([
                InlineKeyboardButton(
                    text="New Invite Code",
                    callback_data="family:newinvite",
                ),
            ])
        buttons.append([
            InlineKeyboardButton(
                text="Leave Household",
                callback_data="family:leave",
            ),
        ])
    else:
        buttons.append([
            InlineKeyboardButton(
                text="Create Household",
                callback_data="family:create",
            ),
        ])
        buttons.append([
            InlineKeyboardButton(
                text="Join Household",
                callback_data="family:join",
            ),
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def confirm_leave_keyboard() -> InlineKeyboardMarkup:
    """Create keyboard to confirm leaving household."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Yes, Leave",
                    callback_data="family:confirmleave",
                ),
                InlineKeyboardButton(
                    text="Cancel",
                    callback_data="family:cancelleave",
                ),
            ],
        ]
    )
