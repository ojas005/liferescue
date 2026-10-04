"""Dev server over the fake runtime + real DB:  LIFERESCUE_ENV=local uvicorn tests.dev_app:app (needs DATABASE_URL)."""

from app.main import create_app
from app.settings import Settings
from tests.dev_stack import fake_engine_factory

app = create_app(
    Settings(liferescue_env="local", model_adapter="mock"), run_engine_factory=fake_engine_factory()
)
