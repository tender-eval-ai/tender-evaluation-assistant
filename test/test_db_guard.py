"""reset_for_tests drops tables, so it refuses any database not named for tests."""
import pytest

from app import db


@pytest.mark.parametrize("dsn", ["postgresql://postgres:dev@localhost:55432/tender",
                                 "postgresql://postgres:dev@localhost:5432/postgres"])
def test_reset_refuses_a_database_not_named_for_tests(dsn):
    with pytest.raises(RuntimeError, match="refusing to reset"):
        db.reset_for_tests(dsn)
