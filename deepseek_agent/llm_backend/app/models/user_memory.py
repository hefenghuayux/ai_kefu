from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, func

from app.core.database import Base


class UserMemoryItem(Base):
    __tablename__ = "user_memory_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_type = Column(String(50), nullable=False, index=True)
    content = Column(Text, nullable=False)
    source_conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True)
    source_message_id = Column(Integer, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    confidence = Column(Float, default=0.8)
    status = Column(String(20), default="active", index=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime, nullable=True)
