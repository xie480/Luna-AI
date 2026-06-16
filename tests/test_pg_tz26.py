import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import String, DateTime, func
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
    # ADD connect_args
    engine = create_async_engine(
        conn_str,
        connect_args={"server_settings": {"timezone": "Asia/Shanghai"}}
    )
    
    async with AsyncSession(engine) as session:
        interaction = InteractionModel(
            id="test_refresh_2",
            session_id="sess",
            message_id="msg",
            user_content="u",
            assistant_content="a"
        )
        session.add(interaction)
        await session.commit()
        await session.refresh(interaction)
        
        print(f"Refreshed created_at: {repr(interaction.created_at)}")
        print(f"isoformat: {interaction.created_at.isoformat()}")
            
    await engine.dispose()

asyncio.run(main())