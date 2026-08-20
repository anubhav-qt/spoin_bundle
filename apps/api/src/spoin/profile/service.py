from __future__ import annotations

import datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from spoin.api.schemas import DailyActivityOut, ProfileStatsOut, UserProfileUpdateIn
from spoin.domain.enums import EngagementKind
from spoin.domain.models import EngagementEvent, User


class ProfileService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def update_profile(self, user_id: UUID, updates: UserProfileUpdateIn) -> User:
        user = await self._session.get(User, user_id)
        if not user:
            raise ValueError("User not found")

        if updates.display_name is not None:
            user.display_name = updates.display_name
        if updates.age is not None:
            user.age = updates.age
        if updates.gender is not None:
            user.gender = updates.gender
        if updates.avatar_icon is not None:
            user.avatar_icon = updates.avatar_icon

        await self._session.commit()
        return user

    async def update_avatar_image(self, user_id: UUID, image_bytes: bytes) -> User:
        user = await self._session.get(User, user_id)
        if not user:
            raise ValueError("User not found")

        user.avatar_image = image_bytes
        await self._session.commit()
        return user

    async def delete_avatar_image(self, user_id: UUID) -> User:
        user = await self._session.get(User, user_id)
        if not user:
            raise ValueError("User not found")

        user.avatar_image = None
        await self._session.commit()
        return user

    async def get_profile_stats(self, user_id: UUID, year: int, month: int) -> ProfileStatsOut:
        # 1. Total cards read & topics
        totals_query = text("""
            SELECT 
                COUNT(id) as total_cards,
                COUNT(DISTINCT topic_id) as total_topics
            FROM engagement_event
            WHERE user_id = :user_id 
              AND kind IN ('explicit_complete', 'dwell_complete')
        """)
        totals_res = await self._session.execute(totals_query, {"user_id": user_id})
        totals_row = totals_res.fetchone()
        total_cards = totals_row.total_cards if totals_row else 0
        total_topics = totals_row.total_topics if totals_row else 0

        # 2. Monthly activity
        month_start = datetime.datetime(year, month, 1, tzinfo=datetime.UTC)
        if month == 12:
            next_month = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.UTC)
        else:
            next_month = datetime.datetime(year, month + 1, 1, tzinfo=datetime.UTC)

        monthly_query = text("""
            SELECT 
                date_trunc('day', occurred_at) as day,
                COUNT(*) as cards_read
            FROM engagement_event
            WHERE user_id = :user_id 
              AND kind IN ('explicit_complete', 'dwell_complete')
              AND occurred_at >= :start AND occurred_at < :end
            GROUP BY day
            ORDER BY day
        """)
        monthly_res = await self._session.execute(
            monthly_query, {"user_id": user_id, "start": month_start, "end": next_month}
        )
        monthly_activity = [
            DailyActivityOut(date=row.day.strftime("%Y-%m-%d"), cards_read=row.cards_read)
            for row in monthly_res
        ]

        # 3. Streaks
        streak_query = text("""
            WITH user_days AS (
                SELECT DISTINCT date_trunc('day', occurred_at) as act_date
                FROM engagement_event
                WHERE user_id = :user_id 
                  AND kind IN ('explicit_complete', 'dwell_complete')
            ),
            groups AS (
                SELECT act_date,
                       act_date - (dense_rank() OVER (ORDER BY act_date)) * interval '1 day' AS grp
                FROM user_days
            ),
            streaks AS (
                SELECT min(act_date) as start_date, max(act_date) as end_date, count(*) as streak_length
                FROM groups
                GROUP BY grp
            )
            SELECT start_date, end_date, streak_length
            FROM streaks
            ORDER BY end_date DESC
        """)
        streak_res = await self._session.execute(streak_query, {"user_id": user_id})
        streaks = streak_res.fetchall()

        longest_streak = max([s.streak_length for s in streaks]) if streaks else 0
        current_streak = 0
        
        if streaks:
            last_streak = streaks[0]
            today = datetime.datetime.now(datetime.UTC).replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday = today - datetime.timedelta(days=1)
            # act_date from postgres date_trunc('day') comes back as naive datetime or with tz depending on driver,
            # so we ensure timezone awareness for comparison
            end_date = last_streak.end_date
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=datetime.UTC)
            
            if end_date == today or end_date == yesterday:
                current_streak = last_streak.streak_length

        return ProfileStatsOut(
            current_streak=current_streak,
            longest_streak=longest_streak,
            total_cards_read=total_cards,
            total_topics=total_topics,
            monthly_activity=monthly_activity,
        )
