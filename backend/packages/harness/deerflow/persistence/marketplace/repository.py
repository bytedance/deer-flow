"""SQLAlchemy-backed marketplace repository.

Provides CRUD operations for marketplace listings, reviews, and install records.
Each method acquires its own short-lived session.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.marketplace.model import (
    MarketplaceInstallRecordRow,
    MarketplaceListingRow,
    MarketplaceReviewRow,
)


class MarketplaceRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _row_to_dict(row: MarketplaceListingRow | MarketplaceReviewRow | MarketplaceInstallRecordRow) -> dict:
        d = row.to_dict()
        for key in ("created_at", "updated_at", "installed_at"):
            val = d.get(key)
            if isinstance(val, datetime):
                d[key] = val.isoformat()
        return d

    # -------------------------------------------------------------------------
    # Listings
    # -------------------------------------------------------------------------

    async def create_listing(
        self,
        *,
        tenant_id: str,
        template_id: str,
        template_version: int,
        display_name: str,
        description: str,
        visibility: str = "tenant",
        category: str | None = None,
        tags: list[str] | None = None,
        icon: str | None = None,
        created_by: str,
    ) -> dict:
        """Create a new marketplace listing."""
        row = MarketplaceListingRow(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            template_id=template_id,
            template_version=template_version,
            display_name=display_name,
            description=description,
            visibility=visibility,
            category=category,
            tags=tags,
            icon=icon,
            avg_rating=0.0,
            review_count=0,
            install_count=0,
            status="active",
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._row_to_dict(row)

    async def get_listing(self, listing_id: str) -> dict | None:
        """Get a listing by ID."""
        async with self._sf() as session:
            row = await session.get(MarketplaceListingRow, listing_id)
            if row is None:
                return None
            return self._row_to_dict(row)

    async def get_listing_by_template(self, template_id: str) -> dict | None:
        """Get a listing by template_id."""
        async with self._sf() as session:
            stmt = select(MarketplaceListingRow).where(MarketplaceListingRow.template_id == template_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._row_to_dict(row)

    async def list_listings(
        self,
        *,
        tenant_id: str | None = None,
        visibility: str | None = None,
        category: str | None = None,
        search: str | None = None,
        status: str = "active",
        sort_by: str = "created_at",
        sort_order: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List marketplace listings with filters and pagination.

        Returns (listings, total_count).
        """
        stmt = select(MarketplaceListingRow)
        count_stmt = select(func.count()).select_from(MarketplaceListingRow)

        conditions = []
        if tenant_id is not None:
            conditions.append(MarketplaceListingRow.tenant_id == tenant_id)
        if visibility is not None:
            conditions.append(MarketplaceListingRow.visibility == visibility)
        if category is not None:
            conditions.append(MarketplaceListingRow.category == category)
        if status is not None:
            conditions.append(MarketplaceListingRow.status == status)
        if search:
            search_pattern = f"%{search}%"
            conditions.append(
                MarketplaceListingRow.display_name.ilike(search_pattern)
                | MarketplaceListingRow.description.ilike(search_pattern)
            )

        if conditions:
            stmt = stmt.where(and_(*conditions))
            count_stmt = count_stmt.where(and_(*conditions))

        # Sort: boost featured/industrial templates first, then apply user sort
        sort_col = getattr(MarketplaceListingRow, sort_by, MarketplaceListingRow.created_at)
        featured_expr = case(
            (MarketplaceListingRow.category == "industrial", 1),
            else_=0,
        ).desc()
        if sort_order == "desc":
            stmt = stmt.order_by(featured_expr, sort_col.desc())
        else:
            stmt = stmt.order_by(featured_expr, sort_col.asc())

        stmt = stmt.offset(offset).limit(limit)

        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())

            count_result = await session.execute(count_stmt)
            total = count_result.scalar_one()

            return [self._row_to_dict(r) for r in rows], total

    async def update_listing(
        self,
        listing_id: str,
        **updates: Any,
    ) -> dict | None:
        """Update a listing. Returns updated dict or None if not found."""
        if not updates:
            return await self.get_listing(listing_id)

        updates["updated_at"] = datetime.now(UTC)

        async with self._sf() as session:
            stmt = update(MarketplaceListingRow).where(MarketplaceListingRow.id == listing_id).values(**updates)
            result = await session.execute(stmt)
            if result.rowcount == 0:
                return None
            await session.commit()
            return await self.get_listing(listing_id)

    async def delete_listing(self, listing_id: str) -> bool:
        """Delete a listing. Returns True if deleted."""
        async with self._sf() as session:
            row = await session.get(MarketplaceListingRow, listing_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    # -------------------------------------------------------------------------
    # Reviews
    # -------------------------------------------------------------------------

    async def create_review(
        self,
        *,
        listing_id: str,
        tenant_id: str,
        user_id: str,
        rating: int,
        comment: str | None = None,
    ) -> dict:
        """Create a review for a listing. Updates listing's avg_rating and review_count."""
        if rating < 1 or rating > 5:
            raise ValueError(f"rating must be 1-5, got {rating}")

        review_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        row = MarketplaceReviewRow(
            id=review_id,
            listing_id=listing_id,
            tenant_id=tenant_id,
            user_id=user_id,
            rating=rating,
            comment=comment,
            created_at=now,
        )

        async with self._sf() as session:
            session.add(row)
            await session.commit()

            # Update listing aggregate
            avg_stmt = select(func.avg(MarketplaceReviewRow.rating)).where(
                MarketplaceReviewRow.listing_id == listing_id
            )
            count_stmt = select(func.count()).select_from(MarketplaceReviewRow).where(
                MarketplaceReviewRow.listing_id == listing_id
            )

            avg_result = await session.execute(avg_stmt)
            count_result = await session.execute(count_stmt)

            avg_rating = avg_result.scalar_one() or 0.0
            review_count = count_result.scalar_one() or 0

            update_stmt = (
                update(MarketplaceListingRow)
                .where(MarketplaceListingRow.id == listing_id)
                .values(avg_rating=avg_rating, review_count=review_count, updated_at=now)
            )
            await session.execute(update_stmt)
            await session.commit()

            await session.refresh(row)
            return self._row_to_dict(row)

    async def list_reviews(
        self,
        listing_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List reviews for a listing. Returns (reviews, total_count)."""
        stmt = select(MarketplaceReviewRow).where(MarketplaceReviewRow.listing_id == listing_id)
        count_stmt = (
            select(func.count())
            .select_from(MarketplaceReviewRow)
            .where(MarketplaceReviewRow.listing_id == listing_id)
        )

        stmt = stmt.order_by(MarketplaceReviewRow.created_at.desc()).offset(offset).limit(limit)

        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())

            count_result = await session.execute(count_stmt)
            total = count_result.scalar_one()

            return [self._row_to_dict(r) for r in rows], total

    async def get_review(self, review_id: str) -> dict | None:
        """Get a review by ID."""
        async with self._sf() as session:
            row = await session.get(MarketplaceReviewRow, review_id)
            if row is None:
                return None
            return self._row_to_dict(row)

    async def get_user_review(self, listing_id: str, user_id: str) -> dict | None:
        """Get a user's review for a specific listing."""
        async with self._sf() as session:
            stmt = select(MarketplaceReviewRow).where(
                MarketplaceReviewRow.listing_id == listing_id,
                MarketplaceReviewRow.user_id == user_id,
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return self._row_to_dict(row)

    async def delete_review(self, review_id: str) -> bool:
        """Delete a review and update listing aggregates. Returns True if deleted."""
        async with self._sf() as session:
            row = await session.get(MarketplaceReviewRow, review_id)
            if row is None:
                return False

            listing_id = row.listing_id
            await session.delete(row)
            await session.commit()

            # Recalculate listing aggregate
            avg_stmt = select(func.avg(MarketplaceReviewRow.rating)).where(
                MarketplaceReviewRow.listing_id == listing_id
            )
            count_stmt = select(func.count()).select_from(MarketplaceReviewRow).where(
                MarketplaceReviewRow.listing_id == listing_id
            )

            avg_result = await session.execute(avg_stmt)
            count_result = await session.execute(count_stmt)

            avg_rating = avg_result.scalar_one() or 0.0
            review_count = count_result.scalar_one() or 0

            update_stmt = (
                update(MarketplaceListingRow)
                .where(MarketplaceListingRow.id == listing_id)
                .values(avg_rating=avg_rating, review_count=review_count, updated_at=datetime.now(UTC))
            )
            await session.execute(update_stmt)
            await session.commit()

            return True

    # -------------------------------------------------------------------------
    # Install Records
    # -------------------------------------------------------------------------

    async def record_install(
        self,
        *,
        listing_id: str,
        tenant_id: str,
        user_id: str,
        target_template_id: str,
        source_version: int,
    ) -> dict:
        """Record a template installation and increment listing's install_count."""
        now = datetime.now(UTC)
        row = MarketplaceInstallRecordRow(
            id=str(uuid.uuid4()),
            listing_id=listing_id,
            tenant_id=tenant_id,
            user_id=user_id,
            target_template_id=target_template_id,
            source_version=source_version,
            installed_at=now,
        )

        async with self._sf() as session:
            session.add(row)
            await session.commit()

            # Increment install count
            update_stmt = (
                update(MarketplaceListingRow)
                .where(MarketplaceListingRow.id == listing_id)
                .values(install_count=MarketplaceListingRow.install_count + 1, updated_at=now)
            )
            await session.execute(update_stmt)
            await session.commit()

            await session.refresh(row)
            return self._row_to_dict(row)

    async def list_installs(
        self,
        listing_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict], int]:
        """List install records for a listing. Returns (records, total_count)."""
        stmt = select(MarketplaceInstallRecordRow).where(MarketplaceInstallRecordRow.listing_id == listing_id)
        count_stmt = (
            select(func.count())
            .select_from(MarketplaceInstallRecordRow)
            .where(MarketplaceInstallRecordRow.listing_id == listing_id)
        )

        stmt = stmt.order_by(MarketplaceInstallRecordRow.installed_at.desc()).offset(offset).limit(limit)

        async with self._sf() as session:
            result = await session.execute(stmt)
            rows = list(result.scalars())

            count_result = await session.execute(count_stmt)
            total = count_result.scalar_one()

            return [self._row_to_dict(r) for r in rows], total

    async def get_user_installs(
        self,
        tenant_id: str,
        user_id: str,
        *,
        limit: int = 100,
    ) -> list[dict]:
        """Get all installations by a user in a tenant."""
        stmt = (
            select(MarketplaceInstallRecordRow)
            .where(
                MarketplaceInstallRecordRow.tenant_id == tenant_id,
                MarketplaceInstallRecordRow.user_id == user_id,
            )
            .order_by(MarketplaceInstallRecordRow.installed_at.desc())
            .limit(limit)
        )

        async with self._sf() as session:
            result = await session.execute(stmt)
            return [self._row_to_dict(r) for r in result.scalars()]
