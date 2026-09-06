BEGIN;

-- ── 1. User ────────────────────────────────────────────────────────────────
-- Đây là user test; submitted_by_user_id trong API phải khớp với UUID này.
INSERT INTO users (id, email, display_name)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'local-test@example.test',
    'Local Test'
)
ON CONFLICT DO NOTHING;

-- ── 2. Course ──────────────────────────────────────────────────────────────
INSERT INTO courses (id, code, name, term, created_by)
VALUES (
    '00000000-0000-4000-8000-000000000002',
    'DACN-LOCAL',
    'Local course',
    'HK261',
    '00000000-0000-4000-8000-000000000001'
)
ON CONFLICT DO NOTHING;

-- ── 3. Course membership (user là student trong course) ────────────────────
INSERT INTO course_memberships (course_id, user_id, role)
VALUES (
    '00000000-0000-4000-8000-000000000002',
    '00000000-0000-4000-8000-000000000001',
    'student'
)
ON CONFLICT DO NOTHING;

-- ── 4. Project (status phải là "open") ────────────────────────────────────
-- API kiểm tra project.status = "open" khi tạo submission.
INSERT INTO projects (id, course_id, title, status, created_by)
VALUES (
    '00000000-0000-4000-8000-000000000003',
    '00000000-0000-4000-8000-000000000002',
    'Local project',
    'open',
    '00000000-0000-4000-8000-000000000001'
)
ON CONFLICT DO NOTHING;

-- ── 5. Project group ───────────────────────────────────────────────────────
INSERT INTO project_groups (id, project_id, name)
VALUES (
    '00000000-0000-4000-8000-000000000004',
    '00000000-0000-4000-8000-000000000003',
    'Local group'
)
ON CONFLICT DO NOTHING;

-- ── 6. Group member (user phải là member của group) ────────────────────────
-- API kiểm tra group_members khi tạo submission.
INSERT INTO group_members (group_id, project_id, user_id)
VALUES (
    '00000000-0000-4000-8000-000000000004',
    '00000000-0000-4000-8000-000000000003',
    '00000000-0000-4000-8000-000000000001'
)
ON CONFLICT DO NOTHING;

-- ── 7. Rubric version (status phải là "published") ─────────────────────────
-- API kiểm tra rubric_versions.status = "published" khi tạo submission.
INSERT INTO rubric_versions (id, project_id, version_no, status, policy_version, published_at, created_by)
VALUES (
    '00000000-0000-4000-8000-000000000005',
    '00000000-0000-4000-8000-000000000003',
    1,
    'published',
    '1.0',
    NOW(),
    '00000000-0000-4000-8000-000000000001'
)
ON CONFLICT DO NOTHING;

COMMIT;
