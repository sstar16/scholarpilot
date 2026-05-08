"""Smoke test：app 能 import + 至少 20 个 routes。"""


def test_app_imports():
    from app.main import app

    assert app is not None
    routes = list(app.routes)
    print(f"\nrouted endpoints: {len(routes)}")
    for r in routes[:50]:
        path = getattr(r, "path", None)
        if path:
            print(f"  - {path}")
    assert len(routes) > 20, f"only {len(routes)} routes (expected > 20)"


def test_settings_loads():
    from app.config import settings

    assert settings.app_name
    assert settings.min_client_version == "0.2.0"
    assert settings.disable_fulltext_browser is True


def test_models_register():
    """所有 8 张表必须在 Base.metadata 注册。"""
    from app.database import Base
    import app.models  # noqa: F401

    table_names = set(Base.metadata.tables.keys())
    expected = {
        "users",
        "invitation_codes",
        "refresh_tokens",
        "dev_logs",
        "site_feedback",
        "document_import_jobs",
        "user_documents",
        "user_notification_settings",
    }
    missing = expected - table_names
    assert not missing, f"models missing from metadata: {missing}"
