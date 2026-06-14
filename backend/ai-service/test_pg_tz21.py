import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import String, DateTime, func, text
from app.config.settings import settings

Base = declarative_base()

class InteractionModel(Base):
    __tablename__ = "interactions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_content: Mapped[str] = mapped_column(String(64), nullable=False)
    assistant_content: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

async def main():
    conn_str = f"postgresql+asyncpg://{settings.db_user}:{settings.db_password}@{settings.db_host}:{settings.db_port}/{settings.db_name}"
    engine = create_async_engine(conn_str)
    
    from sqlalchemy import select
    async with AsyncSession(engine) as session:
        result = await session.execute(select(InteractionModel).limit(1))
        row = result.scalars().first()
        if row:
            print(f"ORM created_at: {repr(row.created_at)}")
            print(f"isoformat: {row.created_at.isoformat()}")
            
    await engine.dispose()

asyncio.run(main())