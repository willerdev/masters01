import base64
import os

os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = "test-jwt-secret-test-jwt-secret-test"
os.environ["MASTER_KEY"] = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ["SEED_SAMPLE_DATA"] = "false"
os.environ["SEED_ADMIN_EMAIL"] = ""
os.environ["SEED_ADMIN_PASSWORD"] = ""
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://tradeguard:tradeguard@localhost:5432/tradeguard_test",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import create_app
from app.models import Base


@pytest.fixture(scope="session")
def engine():
    url = os.environ["DATABASE_URL"]
    eng = create_engine(url, pool_pre_ping=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def db(engine):
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(engine):
    from app.core.rate_limit import auth_limiter

    auth_limiter.reset()
    get_settings.cache_clear()
    app = create_app()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(app) as test_client:
        yield test_client
    Base.metadata.drop_all(engine)
