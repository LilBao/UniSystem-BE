import logging
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

logger = logging.getLogger("uvicorn.error")

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)

_IDEMPOTENT_MIGRATION_STATEMENTS: tuple[str, ...] = (
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_reference_documents_normalized_doi
    ON reference_documents (lower(doi))
    WHERE doi IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_reference_documents_canonical_url
    ON reference_documents (canonical_url)
    WHERE canonical_url IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_submission_references_resolution
    ON submission_references (submission_id, resolver_status)
    """,
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_hash text
    """,
    """
    ALTER TABLE users
    DROP CONSTRAINT IF EXISTS users_global_role_check,
    DROP CONSTRAINT IF EXISTS ck_users_global_role
    """,
    """
    ALTER TABLE users
    ADD CONSTRAINT ck_users_global_role
    CHECK (global_role IN ('user', 'student', 'instructor', 'admin'))
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_users_normalized_email
    ON users (lower(email))
    """,
)

_LOCAL_SEED_STATEMENTS: tuple[str, ...] = (
    """
    INSERT INTO users (id, email, display_name, password_hash, global_role, is_active)
    VALUES
        (
            '00000000-0000-4000-8000-000000000001',
            'local-test@example.test',
            'Nguyễn Văn A (Student Leader)',
            '$2b$12$R3oRLA8UNdVlYdHGDAwOiuznu56cLqUtBGhqAdVQZ9exgFketyCh.',
            'student',
            true
        ),
        (
            '00000000-0000-4000-8000-000000000010',
            'admin@example.test',
            'System Administrator',
            '$2b$12$R3oRLA8UNdVlYdHGDAwOiuznu56cLqUtBGhqAdVQZ9exgFketyCh.',
            'admin',
            true
        ),
        (
            '00000000-0000-4000-8000-000000000011',
            'instructor@example.test',
            'TS. Trần Văn Giảng Viên',
            '$2b$12$R3oRLA8UNdVlYdHGDAwOiuznu56cLqUtBGhqAdVQZ9exgFketyCh.',
            'instructor',
            true
        ),
        (
            '00000000-0000-4000-8000-000000000012',
            'ta@example.test',
            'Lê Thị Trợ Giảng (TA)',
            '$2b$12$R3oRLA8UNdVlYdHGDAwOiuznu56cLqUtBGhqAdVQZ9exgFketyCh.',
            'user',
            true
        ),
        (
            '00000000-0000-4000-8000-000000000013',
            'student2@example.test',
            'Phạm Minh B (Student Member)',
            '$2b$12$R3oRLA8UNdVlYdHGDAwOiuznu56cLqUtBGhqAdVQZ9exgFketyCh.',
            'student',
            true
        )
    ON CONFLICT (id) DO UPDATE
    SET
        password_hash = COALESCE(users.password_hash, EXCLUDED.password_hash),
        global_role = EXCLUDED.global_role,
        is_active = true
    """,
    """
    INSERT INTO courses (id, code, name, term, status, created_by)
    VALUES (
        '00000000-0000-4000-8000-000000000002',
        'DACN-LOCAL',
        'Đồ án chuyên ngành Công nghệ phần mềm',
        'HK261',
        'active',
        '00000000-0000-4000-8000-000000000011'
    )
    ON CONFLICT (id) DO NOTHING
    """,
    """
    INSERT INTO course_memberships (course_id, user_id, role)
    VALUES
        (
            '00000000-0000-4000-8000-000000000002',
            '00000000-0000-4000-8000-000000000011',
            'instructor'
        ),
        (
            '00000000-0000-4000-8000-000000000002',
            '00000000-0000-4000-8000-000000000012',
            'ta'
        ),
        (
            '00000000-0000-4000-8000-000000000002',
            '00000000-0000-4000-8000-000000000001',
            'student'
        ),
        (
            '00000000-0000-4000-8000-000000000002',
            '00000000-0000-4000-8000-000000000013',
            'student'
        )
    ON CONFLICT (course_id, user_id) DO NOTHING
    """,
    """
    INSERT INTO course_memberships (course_id, user_id, role)
    SELECT '00000000-0000-4000-8000-000000000002', u.id, 'student'
    FROM users u
    WHERE u.global_role IN ('user', 'student')
    ON CONFLICT (course_id, user_id) DO NOTHING
    """,
    """
    INSERT INTO projects (id, course_id, title, description, max_score, status, created_by)
    VALUES (
        '00000000-0000-4000-8000-000000000003',
        '00000000-0000-4000-8000-000000000002',
        'Local project - Hệ thống tự động đánh giá đồ án',
        'Đồ án chuyên ngành: Xây dựng pipeline tự động thẩm định báo cáo PDF và đối soát mã nguồn.',
        10.000,
        'open',
        '00000000-0000-4000-8000-000000000011'
    )
    ON CONFLICT (id) DO UPDATE
    SET status = 'open'
    """,
    """
    INSERT INTO project_groups (id, project_id, name, status)
    VALUES
        (
            '00000000-0000-4000-8000-000000000004',
            '00000000-0000-4000-8000-000000000003',
            'Local group',
            'active'
        ),
        (
            '00000000-0000-4000-8000-000000000006',
            '00000000-0000-4000-8000-000000000003',
            'Group 02 - Capstone Team',
            'active'
        )
    ON CONFLICT (id) DO NOTHING
    """,
    """
    INSERT INTO group_members (group_id, project_id, user_id, role)
    VALUES
        (
            '00000000-0000-4000-8000-000000000004',
            '00000000-0000-4000-8000-000000000003',
            '00000000-0000-4000-8000-000000000001',
            'leader'
        ),
        (
            '00000000-0000-4000-8000-000000000004',
            '00000000-0000-4000-8000-000000000003',
            '00000000-0000-4000-8000-000000000013',
            'member'
        )
    ON CONFLICT (project_id, user_id) DO NOTHING
    """,
    """
    INSERT INTO group_members (group_id, project_id, user_id, role)
    SELECT
        '00000000-0000-4000-8000-000000000004',
        '00000000-0000-4000-8000-000000000003',
        u.id,
        'member'
    FROM users u
    WHERE u.global_role IN ('user', 'student')
      AND u.id NOT IN (
          '00000000-0000-4000-8000-000000000010',
          '00000000-0000-4000-8000-000000000011',
          '00000000-0000-4000-8000-000000000012'
      )
    ON CONFLICT (project_id, user_id) DO NOTHING
    """,
    """
    INSERT INTO rubric_versions (
        id, project_id, version_no, status, policy_version, published_at, created_by
    )
    VALUES (
        '00000000-0000-4000-8000-000000000005',
        '00000000-0000-4000-8000-000000000003',
        1,
        'published',
        '1.0',
        NOW(),
        '00000000-0000-4000-8000-000000000011'
    )
    ON CONFLICT (id) DO NOTHING
    """,
    """
    INSERT INTO rubric_criteria (
        id, rubric_version_id, code, title, description, weight, min_score, max_score, ordinal
    )
    VALUES
        (
            '00000000-0000-4000-8000-000000000021',
            '00000000-0000-4000-8000-000000000005',
            'C1',
            'Cấu trúc báo cáo & Trích dẫn học thuật',
            'Trình bày rõ ràng, đầy đủ căn cứ lý thuyết và trích dẫn chính xác.',
            0.300000,
            0.000,
            10.000,
            1
        ),
        (
            '00000000-0000-4000-8000-000000000022',
            '00000000-0000-4000-8000-000000000005',
            'C2',
            'Kiến trúc hệ thống & Độ nhất quán Code - Báo cáo',
            'Thiết kế kiến trúc hợp lý, mã nguồn khớp với các tuyên bố trong báo cáo.',
            0.400000,
            0.000,
            10.000,
            2
        ),
        (
            '00000000-0000-4000-8000-000000000023',
            '00000000-0000-4000-8000-000000000005',
            'C3',
            'Thực nghiệm, Kiểm thử & Đánh giá kết quả',
            'Có kịch bản kiểm thử, số liệu thực nghiệm minh bạch và phân tích kết quả.',
            0.300000,
            0.000,
            10.000,
            3
        )
    ON CONFLICT (id) DO NOTHING
    """,
)


async def ensure_schema_migrations() -> None:
    """Apply idempotent incremental migrations and local seed data if base schema exists."""
    try:
        settings = get_settings()
        async with engine.begin() as conn:
            users_table = await conn.scalar(text("SELECT to_regclass('public.users')"))
            if users_table is None:
                logger.warning(
                    "Database table 'public.users' does not exist yet; "
                    "run db/migrations/001_initial_schema.sql first."
                )
                return

            for statement in _IDEMPOTENT_MIGRATION_STATEMENTS:
                await conn.execute(text(statement))

            if settings.app_env == "local":
                for statement in _LOCAL_SEED_STATEMENTS:
                    await conn.execute(text(statement))
        logger.info(
            "Database incremental migrations and local seed data verified "
            "(002_ref_resolution, 003_auth_and_rbac, seed_local)."
        )
    except Exception as exc:
        logger.warning("Could not auto-apply incremental database migrations on startup: %s", exc)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionFactory() as session:
        async with session.begin():
            yield session
