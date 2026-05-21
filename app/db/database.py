from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.config import settings

# Create the database engine using the URL from .env
engine = create_async_engine(
    settings.database_url,
    echo=True,   # logs every SQL query — useful during development
)

# Session factory — creates database sessions on demand
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Base class — all your database models will inherit from this
class Base(DeclarativeBase):
    pass

# Dependency — FastAPI calls this to get a database session per request
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session