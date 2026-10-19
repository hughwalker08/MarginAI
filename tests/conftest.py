import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Tests must not depend on the developer's .env (the API loads it at import): start from a neutral environment."""
    for name in ("GOOGLE_CLIENT_ID", "ADMIN_EMAILS", "ALLOW_PUBLIC_HOSTS", "PUBLIC_DEMO", "SYNC_INTERVAL_MINUTES",
                 "SHOPIFY_ALLOWED_SHOPS"):
        monkeypatch.delenv(name, raising=False)
