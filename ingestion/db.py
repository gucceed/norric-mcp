import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not _DATABASE_URL:
    import warnings
    warnings.warn("DATABASE_URL not set — DB operations will fail at runtime")

# Ensure we use the sync psycopg2 driver — asyncpg requires async context
# which is incompatible with this synchronous Session-based code.
_url = (_DATABASE_URL or "postgresql://localhost/norric").replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
).replace(
    "postgres+asyncpg://", "postgresql+psycopg2://"
).replace(
    "postgres://", "postgresql+psycopg2://"
)
if _url.startswith("postgresql://") and "psycopg2" not in _url:
    _url = _url.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(
    _url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"connect_timeout": 10},
)

Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_session():
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def execute_sql_file(path: str) -> None:
    sql = open(path).read()
    with engine.connect() as conn:
        conn.execute(text(sql))
        conn.commit()
