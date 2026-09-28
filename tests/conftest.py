import pytest

from trender.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, demo_mode="on", db_path=str(tmp_path / "t.db"), refresh_interval_hours=0,
                    pytrends_enabled=False, olx_enabled=False, printables_enabled=False)
