from datetime import time

from sqlalchemy import (
    BigInteger, Boolean, Column, Date, DateTime, ForeignKey,
    Integer, String, Text, Time, func
)
from sqlalchemy import JSON
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String(255))
    first_name = Column(String(255))
    language_code = Column(String(10))
    timezone = Column(String(50), default="Europe/Moscow")
    correction_mode = Column(String(20), default="balanced")
    formality_meter = Column(Boolean, default=False)
    topic_pack = Column(String(50), default="general")
    digest_time = Column(Time, default=time(21, 0))
    notifications = Column(Boolean, default=True)
    xp = Column(Integer, default=0)
    level = Column(String(20), default="newbie")
    streak = Column(Integer, default=0)
    last_active_date = Column(Date)
    business_connection_id = Column(String(255))
    groq_api_key = Column(String(255))
    phrase_last_sent = Column(Date)
    weekly_last_sent = Column(Date)
    vocab_reminded_at = Column(DateTime)
    api_balance_initial = Column(String(50))   # user-entered starting balance
    api_balance_set_at = Column(DateTime)      # when it was set
    challenge_last_sent = Column(Date)         # last daily challenge date
    checkup_last_sent = Column(Date)           # last end-of-day checkup date
    english_level = Column(String(10))         # A1/A2/B1/B2/C1 from level test
    created_at = Column(DateTime, server_default=func.now())

    errors = relationship("Error", back_populates="user")
    messages = relationship("Message", back_populates="user")
    vocabulary = relationship("Vocabulary", back_populates="user")
    grammar_usages = relationship("GrammarUsage", back_populates="user")
    achievements = relationship("Achievement", back_populates="user")


class Error(Base):
    __tablename__ = "errors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    chat_id = Column(BigInteger)
    original_text = Column(Text)
    corrected_text = Column(Text)
    category = Column(String(50))
    rule_name = Column(String(255))
    short_explanation = Column(Text)
    detailed_explanation = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="errors")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    chat_id = Column(BigInteger)
    has_errors = Column(Boolean)
    error_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="messages")


class Vocabulary(Base):
    __tablename__ = "vocabulary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    word = Column(String(255))
    translation = Column(Text)
    example = Column(Text)
    source_chat = Column(BigInteger)
    box = Column(Integer, default=1)
    next_review = Column(DateTime)
    times_reviewed = Column(Integer, default=0)
    times_correct = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="vocabulary")


class GrammarUsage(Base):
    __tablename__ = "grammar_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    construction = Column(String(100))
    times_used = Column(Integer, default=0)
    last_used = Column(DateTime)
    first_used = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="grammar_usages")


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    achievement_key = Column(String(100))
    achieved_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="achievements")


class XpLog(Base):
    __tablename__ = "xp_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    amount = Column(Integer)
    reason = Column(String(255))
    created_at = Column(DateTime, server_default=func.now())


class Battle(Base):
    __tablename__ = "battles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user1_id = Column(BigInteger, ForeignKey("users.id"))
    user2_id = Column(BigInteger, ForeignKey("users.id"))
    started_at = Column(DateTime, server_default=func.now())
    active = Column(Boolean, default=True)


class WordCache(Base):
    """Cache for word lookups — avoids repeated GPT calls for the same word."""
    __tablename__ = "word_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    word = Column(String(255), unique=True, index=True)
    data = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())


class RoleplaySession(Base):
    __tablename__ = "roleplay_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    scenario = Column(String(100))
    messages = Column(JSON)
    grade = Column(String(2))
    feedback = Column(Text)
    created_at = Column(DateTime, server_default=func.now())


class DailyMessageBuffer(Base):
    """Accumulates user's English messages during the day for end-of-day analysis."""
    __tablename__ = "daily_message_buffer"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"))
    text = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
