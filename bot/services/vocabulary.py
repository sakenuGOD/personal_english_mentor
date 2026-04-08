from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import LEITNER_INTERVALS
from bot.db.models import Vocabulary


async def add_word(
    session: AsyncSession,
    user_id: int,
    word: str,
    translation: str,
    example: str = "",
    source_chat: int | None = None,
) -> Vocabulary | None:
    existing = await session.execute(
        select(Vocabulary).where(
            Vocabulary.user_id == user_id,
            Vocabulary.word == word.lower(),
        )
    )
    if existing.scalar_one_or_none():
        return None

    vocab = Vocabulary(
        user_id=user_id,
        word=word.lower(),
        translation=translation,
        example=example,
        source_chat=source_chat,
        box=1,
        next_review=datetime.utcnow() + timedelta(days=LEITNER_INTERVALS[1]),
    )
    session.add(vocab)
    await session.commit()
    return vocab


async def get_words_for_review(session: AsyncSession, user_id: int, limit: int = 5) -> list[Vocabulary]:
    result = await session.execute(
        select(Vocabulary)
        .where(
            Vocabulary.user_id == user_id,
            Vocabulary.next_review <= datetime.utcnow(),
        )
        .order_by(Vocabulary.next_review)
        .limit(limit)
    )
    return list(result.scalars().all())


async def review_word(session: AsyncSession, word_id: int, remembered: bool):
    result = await session.execute(
        select(Vocabulary).where(Vocabulary.id == word_id)
    )
    vocab = result.scalar_one_or_none()
    if not vocab:
        return

    vocab.times_reviewed += 1
    if remembered:
        vocab.times_correct += 1
        vocab.box = min(vocab.box + 1, 5)
    else:
        vocab.box = 1

    interval = LEITNER_INTERVALS.get(vocab.box, 1)
    vocab.next_review = datetime.utcnow() + timedelta(days=interval)
    await session.commit()


async def get_all_words(session: AsyncSession, user_id: int, limit: int = 10, offset: int = 0) -> list[Vocabulary]:
    result = await session.execute(
        select(Vocabulary)
        .where(Vocabulary.user_id == user_id)
        .order_by(Vocabulary.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_vocab_stats(session: AsyncSession, user_id: int) -> dict:
    result = await session.execute(
        select(Vocabulary).where(Vocabulary.user_id == user_id)
    )
    words = list(result.scalars().all())
    total = len(words)
    due = sum(1 for w in words if w.next_review and w.next_review <= datetime.utcnow())
    mastered = sum(1 for w in words if w.box >= 4)
    return {"total": total, "due_today": due, "mastered": mastered}
