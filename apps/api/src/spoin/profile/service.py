from __future__ import annotations

import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from spoin.api.schemas import (
    DailyActivityOut,
    ExportedCardRefOut,
    ExportedNoteOut,
    ExportedTopicOut,
    ProfileExportOut,
    ProfileStatsOut,
    UserOut,
    UserProfileUpdateIn,
)
from spoin.domain.models import (
    Card,
    CardBookmark,
    CardLike,
    CardNote,
    Topic,
    User,
    UserTopic,
    UserTopicProgress,
)
from spoin.profile.images import ValidatedImage


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
        if updates.daily_card_goal is not None:
            user.daily_card_goal = updates.daily_card_goal

        await self._session.commit()
        return user

    async def update_avatar_image(self, user_id: UUID, image: ValidatedImage) -> User:
        user = await self._session.get(User, user_id)
        if not user:
            raise ValueError("User not found")

        # All three move together, always — `has_avatar_image` is only correct
        # because nothing else writes it.
        user.avatar_image = image.data
        user.avatar_media_type = image.media_type
        user.has_avatar_image = True
        await self._session.commit()
        return user

    async def delete_avatar_image(self, user_id: UUID) -> User:
        user = await self._session.get(User, user_id)
        if not user:
            raise ValueError("User not found")

        user.avatar_image = None
        user.avatar_media_type = None
        user.has_avatar_image = False
        await self._session.commit()
        return user

    async def load_avatar_image(self, user_id: UUID) -> tuple[bytes, str]:
        """The bytes, with the blob explicitly undeferred.

        `avatar_image` is deferred (domain/models/topic.py), so this is the one
        place that asks for it — everywhere else reads `has_avatar_image` and
        never touches the column at all.
        """

        row = (
            await self._session.execute(
                select(User).where(User.id == user_id).options(undefer(User.avatar_image))
            )
        ).scalar_one_or_none()
        if row is None or row.avatar_image is None:
            raise LookupError("No avatar image found")
        return row.avatar_image, row.avatar_media_type or "application/octet-stream"

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
                SELECT min(act_date) as start_date,
                       max(act_date) as end_date,
                       count(*) as streak_length
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
            today = datetime.datetime.now(datetime.UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            yesterday = today - datetime.timedelta(days=1)
            # act_date from postgres date_trunc('day') comes back as naive
            # datetime or with tz depending on driver, so ensure timezone
            # awareness before comparing.
            end_date = last_streak.end_date
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=datetime.UTC)

            if end_date in (today, yesterday):
                current_streak = last_streak.streak_length

        return ProfileStatsOut(
            current_streak=current_streak,
            longest_streak=longest_streak,
            total_cards_read=total_cards,
            total_topics=total_topics,
            monthly_activity=monthly_activity,
        )

    async def export_data(self, user_id: UUID) -> ProfileExportOut:
        """Everything this user has produced, in one pass.

        Six bounded queries, each already indexed by user_id, and no card
        bodies: the corpus is shared content, the user's relationship to it is
        what belongs to them. Same serving-layer contract as the rest of this
        file -- no generation, no embedding, no LLM.
        """
        user = await self._session.get(User, user_id)
        if not user:
            raise ValueError("User not found")

        topics = [
            ExportedTopicOut(
                topic_id=row.UserTopic.topic_id,
                name=row.UserTopic.display_name,
                is_custom=row.UserTopic.is_custom,
                current_difficulty=row.current_difficulty,
                followed_at=row.UserTopic.created_at,
            )
            for row in (
                await self._session.execute(
                    select(UserTopic, UserTopicProgress.current_difficulty)
                    .outerjoin(
                        UserTopicProgress,
                        (UserTopicProgress.user_id == UserTopic.user_id)
                        & (UserTopicProgress.topic_id == UserTopic.topic_id),
                    )
                    .where(UserTopic.user_id == user_id)
                    .order_by(UserTopic.created_at)
                )
            ).all()
        ]

        notes = [
            ExportedNoteOut(
                card_id=note.card_id,
                card_title=card.title,
                topic=topic_name,
                body=note.body,
                updated_at=note.updated_at,
            )
            for note, card, topic_name in (
                await self._session.execute(
                    select(CardNote, Card, Topic.canonical_name)
                    .join(Card, Card.id == CardNote.card_id)
                    .join(Topic, Topic.id == Card.topic_id)
                    .where(CardNote.user_id == user_id)
                    .order_by(CardNote.updated_at.desc())
                )
            ).all()
        ]

        async def _card_refs(
            model: type[CardLike] | type[CardBookmark],
        ) -> list[ExportedCardRefOut]:
            rows = (
                await self._session.execute(
                    select(model.created_at, Card, Topic.canonical_name)
                    .join(Card, Card.id == model.card_id)
                    .join(Topic, Topic.id == Card.topic_id)
                    .where(model.user_id == user_id)
                    .order_by(model.created_at.desc())
                )
            ).all()
            return [
                ExportedCardRefOut(
                    card_id=card.id,
                    title=card.title,
                    topic=topic_name,
                    difficulty=card.difficulty,
                    at=at,
                )
                for at, card, topic_name in rows
            ]

        activity_rows = await self._session.execute(
            text("""
                SELECT date_trunc('day', occurred_at) AS day, COUNT(*) AS cards_read
                FROM engagement_event
                WHERE user_id = :user_id
                  AND kind IN ('explicit_complete', 'dwell_complete')
                GROUP BY day
                ORDER BY day
            """),
            {"user_id": user_id},
        )

        return ProfileExportOut(
            exported_at=datetime.datetime.now(datetime.UTC),
            schema_version=1,
            profile=UserOut.model_validate(user, from_attributes=True),
            topics=topics,
            notes=notes,
            liked_cards=await _card_refs(CardLike),
            saved_cards=await _card_refs(CardBookmark),
            daily_activity=[
                DailyActivityOut(date=r.day.strftime("%Y-%m-%d"), cards_read=r.cards_read)
                for r in activity_rows
            ],
        )
