"""SQLAlchemy models for user profiles and chat history."""

from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    preferences = Column(Text, default="")

    messages = relationship("Message", back_populates="user")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String, index=True)
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="messages")


class Character(Base):
    __tablename__ = "characters"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    system_prompt = Column(Text, default="")
    voice_id = Column(String, default="")
    avatar = Column(String, default="")


class ApiSecret(Base):
    __tablename__ = "api_secrets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    value_enc = Column(Text)  # base64-encoded encrypted payload
    updated_at = Column(DateTime, default=datetime.utcnow)
