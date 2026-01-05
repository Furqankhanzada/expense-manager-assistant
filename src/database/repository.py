"""Repository pattern for database operations."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import secrets

from src.database.models import (
    Category,
    Expense,
    Household,
    LLMConfig,
    SourceType,
    User,
    DEFAULT_CATEGORIES,
)


class UserRepository:
    """Repository for User operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """Get user by Telegram ID."""
        result = await self.session.execute(
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.categories))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: UUID) -> User | None:
        """Get user by UUID."""
        result = await self.session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        """Create a new user with default categories."""
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        self.session.add(user)
        await self.session.flush()

        # Create default categories for the user
        for cat_data in DEFAULT_CATEGORIES:
            category = Category(
                user_id=user.id,
                name=cat_data["name"],
                icon=cat_data["icon"],
                is_default=True,
            )
            self.session.add(category)

        await self.session.flush()
        return user

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> tuple[User, bool]:
        """Get existing user or create a new one. Returns (user, created)."""
        user = await self.get_by_telegram_id(telegram_id)
        if user:
            # Update user info if changed
            if username and user.username != username:
                user.username = username
            if first_name and user.first_name != first_name:
                user.first_name = first_name
            if last_name and user.last_name != last_name:
                user.last_name = last_name
            return user, False

        user = await self.create(telegram_id, username, first_name, last_name)
        return user, True

    async def update_currency(self, user_id: UUID, currency: str) -> None:
        """Update user's default currency."""
        user = await self.get_by_id(user_id)
        if user:
            user.default_currency = currency

    async def complete_setup(self, user_id: UUID, currency: str) -> None:
        """Mark user setup as complete and set currency."""
        user = await self.get_by_id(user_id)
        if user:
            user.default_currency = currency
            user.is_setup_complete = True

    async def join_household(self, user_id: UUID, household_id: UUID) -> bool:
        """Add user to a household."""
        user = await self.get_by_id(user_id)
        if user:
            user.household_id = household_id
            return True
        return False

    async def leave_household(self, user_id: UUID) -> bool:
        """Remove user from their household."""
        user = await self.get_by_id(user_id)
        if user and user.household_id:
            user.household_id = None
            return True
        return False


class HouseholdRepository:
    """Repository for Household operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, name: str, owner_id: UUID) -> Household:
        """Create a new household."""
        invite_code = secrets.token_urlsafe(8)[:10].upper()

        household = Household(
            name=name,
            owner_id=owner_id,
            invite_code=invite_code,
        )
        self.session.add(household)
        await self.session.flush()
        return household

    async def get_by_id(self, household_id: UUID) -> Household | None:
        """Get household by ID."""
        result = await self.session.execute(
            select(Household)
            .where(Household.id == household_id)
            .options(selectinload(Household.members))
        )
        return result.scalar_one_or_none()

    async def get_by_invite_code(self, invite_code: str) -> Household | None:
        """Get household by invite code."""
        result = await self.session.execute(
            select(Household)
            .where(Household.invite_code == invite_code.upper())
            .options(selectinload(Household.members))
        )
        return result.scalar_one_or_none()

    async def get_by_owner(self, owner_id: UUID) -> Household | None:
        """Get household owned by user."""
        result = await self.session.execute(
            select(Household)
            .where(Household.owner_id == owner_id)
            .options(selectinload(Household.members))
        )
        return result.scalar_one_or_none()

    async def get_members(self, household_id: UUID) -> Sequence[User]:
        """Get all members of a household."""
        result = await self.session.execute(
            select(User).where(User.household_id == household_id)
        )
        return result.scalars().all()

    async def get_member_ids(self, household_id: UUID) -> list[UUID]:
        """Get all member IDs of a household."""
        result = await self.session.execute(
            select(User.id).where(User.household_id == household_id)
        )
        return [row[0] for row in result.all()]

    async def regenerate_invite_code(self, household_id: UUID) -> str | None:
        """Generate a new invite code for household."""
        household = await self.get_by_id(household_id)
        if household:
            household.invite_code = secrets.token_urlsafe(8)[:10].upper()
            return household.invite_code
        return None

    async def delete(self, household_id: UUID) -> bool:
        """Delete a household."""
        # First remove all members from household
        await self.session.execute(
            select(User).where(User.household_id == household_id)
        )
        members = await self.get_members(household_id)
        for member in members:
            member.household_id = None

        result = await self.session.execute(
            delete(Household).where(Household.id == household_id)
        )
        return result.rowcount > 0


class CategoryRepository:
    """Repository for Category operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user(self, user_id: UUID) -> Sequence[Category]:
        """Get all categories for a user."""
        result = await self.session.execute(
            select(Category)
            .where(Category.user_id == user_id)
            .order_by(Category.name)
        )
        return result.scalars().all()

    async def get_by_id(self, category_id: UUID) -> Category | None:
        """Get category by ID."""
        result = await self.session.execute(
            select(Category).where(Category.id == category_id)
        )
        return result.scalar_one_or_none()

    async def get_by_name(self, user_id: UUID, name: str) -> Category | None:
        """Get category by name for a user."""
        result = await self.session.execute(
            select(Category).where(
                and_(
                    Category.user_id == user_id,
                    func.lower(Category.name) == func.lower(name),
                )
            )
        )
        return result.scalar_one_or_none()

    async def create(self, user_id: UUID, name: str, icon: str = "") -> Category:
        """Create a new category."""
        category = Category(user_id=user_id, name=name, icon=icon)
        self.session.add(category)
        await self.session.flush()
        return category

    async def delete(self, category_id: UUID) -> bool:
        """Delete a category."""
        result = await self.session.execute(
            delete(Category).where(Category.id == category_id)
        )
        return result.rowcount > 0


class ExpenseRepository:
    """Repository for Expense operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: UUID,
        amount: Decimal,
        description: str | None = None,
        category_id: UUID | None = None,
        currency: str = "USD",
        source_type: SourceType = SourceType.TEXT,
        raw_input: str | None = None,
        expense_date: date | None = None,
        group_chat_id: int | None = None,
    ) -> Expense:
        """Create a new expense.

        Args:
            group_chat_id: If provided, expense is shared in that group.
                          If None, expense is personal (private chat).
        """
        expense = Expense(
            user_id=user_id,
            amount=amount,
            description=description,
            category_id=category_id,
            currency=currency,
            source_type=source_type,
            raw_input=raw_input,
            expense_date=expense_date or date.today(),
            group_chat_id=group_chat_id,
        )
        self.session.add(expense)
        await self.session.flush()
        return expense

    async def get_by_id(self, expense_id: UUID) -> Expense | None:
        """Get expense by ID."""
        result = await self.session.execute(
            select(Expense)
            .where(Expense.id == expense_id)
            .options(selectinload(Expense.category))
        )
        return result.scalar_one_or_none()

    async def get_by_user(
        self,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
        group_chat_id: int | None = None,
    ) -> Sequence[Expense]:
        """Get expenses for a user or group.

        Args:
            user_id: The user's ID
            group_chat_id: If provided, get all expenses for this group.
                          If None, get only personal expenses (private chat).
        """
        if group_chat_id:
            # Group context: get all expenses for this group
            expense_filter = Expense.group_chat_id == group_chat_id
        else:
            # Private context: get only personal expenses (no group)
            expense_filter = and_(
                Expense.user_id == user_id,
                Expense.group_chat_id.is_(None),
            )

        result = await self.session.execute(
            select(Expense)
            .where(expense_filter)
            .options(selectinload(Expense.category), selectinload(Expense.user))
            .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return result.scalars().all()

    async def get_by_date_range(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
        group_chat_id: int | None = None,
    ) -> Sequence[Expense]:
        """Get expenses within a date range."""
        if group_chat_id:
            expense_filter = Expense.group_chat_id == group_chat_id
        else:
            expense_filter = and_(
                Expense.user_id == user_id,
                Expense.group_chat_id.is_(None),
            )

        result = await self.session.execute(
            select(Expense)
            .where(
                and_(
                    expense_filter,
                    Expense.expense_date >= start_date,
                    Expense.expense_date <= end_date,
                )
            )
            .options(selectinload(Expense.category), selectinload(Expense.user))
            .order_by(Expense.expense_date.desc())
        )
        return result.scalars().all()

    async def get_total_by_category(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
        group_chat_id: int | None = None,
    ) -> list[tuple[str, Decimal]]:
        """Get total expenses grouped by category."""
        if group_chat_id:
            expense_filter = Expense.group_chat_id == group_chat_id
        else:
            expense_filter = and_(
                Expense.user_id == user_id,
                Expense.group_chat_id.is_(None),
            )

        result = await self.session.execute(
            select(
                Category.name,
                func.sum(Expense.amount).label("total"),
            )
            .join(Category, Expense.category_id == Category.id, isouter=True)
            .where(
                and_(
                    expense_filter,
                    Expense.expense_date >= start_date,
                    Expense.expense_date <= end_date,
                )
            )
            .group_by(Category.name)
            .order_by(func.sum(Expense.amount).desc())
        )
        return [(row[0] or "Uncategorized", row[1]) for row in result.all()]

    async def get_monthly_total(
        self,
        user_id: UUID,
        year: int,
        month: int,
        group_chat_id: int | None = None,
    ) -> Decimal:
        """Get total expenses for a specific month."""
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        if group_chat_id:
            expense_filter = Expense.group_chat_id == group_chat_id
        else:
            expense_filter = and_(
                Expense.user_id == user_id,
                Expense.group_chat_id.is_(None),
            )

        result = await self.session.execute(
            select(func.coalesce(func.sum(Expense.amount), 0))
            .where(
                and_(
                    expense_filter,
                    Expense.expense_date >= start_date,
                    Expense.expense_date <= end_date,
                )
            )
        )
        return result.scalar() or Decimal(0)

    async def update(
        self,
        expense_id: UUID,
        amount: Decimal | None = None,
        description: str | None = None,
        category_id: UUID | None = None,
    ) -> Expense | None:
        """Update an expense."""
        expense = await self.get_by_id(expense_id)
        if not expense:
            return None

        if amount is not None:
            expense.amount = amount
        if description is not None:
            expense.description = description
        if category_id is not None:
            expense.category_id = category_id

        return expense

    async def delete(self, expense_id: UUID) -> bool:
        """Delete an expense."""
        result = await self.session.execute(
            delete(Expense).where(Expense.id == expense_id)
        )
        return result.rowcount > 0


class LLMConfigRepository:
    """Repository for LLMConfig operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_config(self, user_id: UUID) -> LLMConfig | None:
        """Get the active LLM config for a user."""
        result = await self.session.execute(
            select(LLMConfig).where(
                and_(
                    LLMConfig.user_id == user_id,
                    LLMConfig.is_active == True,
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_by_user(self, user_id: UUID) -> Sequence[LLMConfig]:
        """Get all LLM configs for a user."""
        result = await self.session.execute(
            select(LLMConfig)
            .where(LLMConfig.user_id == user_id)
            .order_by(LLMConfig.created_at.desc())
        )
        return result.scalars().all()

    async def create(
        self,
        user_id: UUID,
        provider: str,
        model: str,
        api_key_encrypted: str | None = None,
    ) -> LLMConfig:
        """Create a new LLM config."""
        # Deactivate existing configs
        await self.session.execute(
            select(LLMConfig)
            .where(LLMConfig.user_id == user_id)
        )
        existing = await self.get_by_user(user_id)
        for config in existing:
            config.is_active = False

        config = LLMConfig(
            user_id=user_id,
            provider=provider,
            model=model,
            api_key_encrypted=api_key_encrypted,
            is_active=True,
        )
        self.session.add(config)
        await self.session.flush()
        return config

    async def set_active(self, config_id: UUID) -> bool:
        """Set a config as the active one."""
        config = await self.session.get(LLMConfig, config_id)
        if not config:
            return False

        # Deactivate other configs for this user
        existing = await self.get_by_user(config.user_id)
        for c in existing:
            c.is_active = c.id == config_id

        return True

    async def delete(self, config_id: UUID) -> bool:
        """Delete an LLM config."""
        result = await self.session.execute(
            delete(LLMConfig).where(LLMConfig.id == config_id)
        )
        return result.rowcount > 0
