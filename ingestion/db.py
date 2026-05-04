import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

_DATABASE_URL = os.environ.get("DATABASE_URL", "")

if not _DATABASE_URL:
    import warnings
    warnings.warn("DATABASE_URL not set — DB operations will fail at runtime")

_url = _DATABASE_URL or "postgresql://localhost/norric"
# asyncpg dialect uses "timeout" not "connect_timeout"; psycopg2 uses "connect_timeout"
_is_asyncpg = "asyncpg" in _url
_connect_args = {"timeout": 10} if _is_asyncpg else {"connect_timeout": 10}

engine = create_engine(
    _url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args=_connect_args,
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
