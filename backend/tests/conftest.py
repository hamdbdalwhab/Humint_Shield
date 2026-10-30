"""Pytest fixtures: hermetic app, database and API client.

The environment is configured *before* the application package is imported so
that ``pydantic-settings`` picks up the test values.  Tests run against an
in-memory SQLite database via ``aiosqlite`` with a ``StaticPool`` so that every
session shares the same database.
"""
from __future__ import annotations

import os

os.environ.setdefault("ENCRYPTION_KEY", "00" * 32)
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-humint-shield")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("BCRYPT_ROUNDS", "4")
os.environ.setdefault("EMAIL_DRY_RUN", "true")
os.environ.setdefault("AUTO_SEED", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("BASE_URL", "http://testserver")
os.environ.setdefault("FROM_EMAIL", "training@testserver")
os.environ.setdefault("BREVO_API_KEY", "")

import uuid  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import EmailTemplate, HumanAsset, Organization, User  # noqa: E402
from app.security import create_access_token, hash_password  # noqa: E402
from app.services.seed import seed_builtin_templates, seed_training_modules  # noqa: E402


@pytest_asyncio.fixture(scope="function")
async def engine():
    """Create a fresh in-memory SQLite database per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def session_factory(engine):
    """Return an ``async_sessionmaker`` bound to the test engine."""
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="function")
async def db(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Yield a session for direct service-level tests."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def app(session_factory):
    """Return a FastAPI app wired to the test database."""
    application = create_app()

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest_asyncio.fixture(scope="function")
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Yield an ``httpx`` client bound to the ASGI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


# --------------------------------------------------------------------------- #
# Domain fixtures
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def organization(db: AsyncSession) -> Organization:
    """Create a test organization."""
    org = Organization(
        name="Acme Test Corporation",
        domain="acmetest.example",
        industry="Technology",
        allowed_test_hours={"start": 9, "end": 17},
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, organization: Organization) -> User:
    """Create an admin user for the organization."""
    user = User(
        username="tester",
        email="tester@acmetest.example",
        password_hash=hash_password("Secret123!"),
        role="admin",
        organization_id=organization.id,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def viewer_user(db: AsyncSession, organization: Organization) -> User:
    """Create a read-only user (for authorization tests)."""
    user = User(
        username="viewer",
        email="viewer@acmetest.example",
        password_hash=hash_password("Secret123!"),
        role="viewer",
        organization_id=organization.id,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def auth_headers(admin_user: User) -> dict[str, str]:
    """Authorization header for the admin user."""
    token = create_access_token(str(admin_user.id), {"role": admin_user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def viewer_headers(viewer_user: User) -> dict[str, str]:
    """Authorization header for the viewer user."""
    token = create_access_token(str(viewer_user.id), {"role": viewer_user.role})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def employee(db: AsyncSession, organization: Organization) -> HumanAsset:
    """Create a single test employee."""
    row = HumanAsset(
        organization_id=organization.id,
        email="jane.doe@acmetest.example",
        first_name="Jane",
        last_name="Doe",
        department="Finance",
        job_title="Controller",
        access_level=3,
        is_active=True,
        behavioral_category="hesitant",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest_asyncio.fixture
async def employees(db: AsyncSession, organization: Organization) -> list[HumanAsset]:
    """Create five test employees."""
    rows = [
        HumanAsset(
            organization_id=organization.id,
            email=f"employee{i}@acmetest.example",
            first_name=f"Employee{i}",
            last_name="Test",
            department="Engineering" if i % 2 else "Finance",
            access_level=(i % 5) + 1,
            is_active=i != 5,
            behavioral_category="hesitant",
        )
        for i in range(1, 6)
    ]
    db.add_all(rows)
    await db.commit()
    for row in rows:
        await db.refresh(row)
    return rows


@pytest_asyncio.fixture
async def builtin_templates(db: AsyncSession, organization: Organization) -> list[EmailTemplate]:
    """Seed the thirteen built-in templates and return them."""
    await seed_builtin_templates(db, organization.id)
    await db.commit()
    from sqlalchemy import select

    result = await db.execute(
        select(EmailTemplate)
        .where(EmailTemplate.organization_id == organization.id)
        .order_by(EmailTemplate.created_at.asc())
    )
    return list(result.scalars().all())


@pytest_asyncio.fixture
async def custom_template(db: AsyncSession, organization: Organization) -> EmailTemplate:
    """Create a single custom (non-built-in) template."""
    template = EmailTemplate(
        organization_id=organization.id,
        name="Custom Test Template",
        subject="Hello {{first_name}} from {{company_name}}",
        body_html=(
            "<p>Hi {{first_name}},</p>"
            '<p><a href="https://portal.example.com/verify">Verify your account</a></p>'
        ),
        difficulty_level=5,
        is_built_in=False,
        is_active=True,
        available_variables=["first_name", "company_name"],
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@pytest_asyncio.fixture
async def qr_template(db: AsyncSession, organization: Organization) -> EmailTemplate:
    """Create a single QR-channel template for quishing campaigns."""
    template = EmailTemplate(
        organization_id=organization.id,
        name="قهوة مجانية",
        subject="قهوة مجانية بانتظارك اليوم",
        body_html="<p>امسح رمز QR لاستلام قسيمتك.</p>",
        difficulty_level=4,
        is_built_in=False,
        is_active=True,
        channel="qr",
        available_variables=["company_name", "department"],
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@pytest_asyncio.fixture
async def training_modules(db: AsyncSession, organization: Organization) -> int:
    """Seed the demo training modules."""
    created = await seed_training_modules(db, organization.id)
    await db.commit()
    return created
