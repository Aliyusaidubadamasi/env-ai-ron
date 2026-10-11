import os
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv()

Base = declarative_base()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg2://env_ai_ron:env_ai_ron@localhost:5432/env_ai_ron")
    return create_engine(database_url, echo=False, future=True)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
