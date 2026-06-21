import asyncio
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).parent.parent
sys.path.append(str(ROOT_DIR))

from app.core.database import Base, engine
from app.core.logger import get_logger
from app.models import ConversationContextItem, UserMemoryItem  # noqa: F401


logger = get_logger(service="create_context_tables")


async def create_context_tables() -> None:
    logger.info("Creating context memory tables if they do not exist...")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Context memory table creation completed.")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(create_context_tables())


if __name__ == "__main__":
    main()
