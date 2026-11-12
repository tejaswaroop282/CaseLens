import pytest


@pytest.fixture
def mongo_db():
    """A throwaway test database on the local MongoDB container (integration tests only)."""
    from pymongo import MongoClient
    client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000, tz_aware=True)
    try:
        client.admin.command("ping")
    except Exception:
        pytest.skip("MongoDB is not running")
    name = "caselens_test"
    client.drop_database(name)
    yield client[name]
    client.drop_database(name)
