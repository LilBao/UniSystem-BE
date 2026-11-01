BEGIN;

-- ── 1. Users (Mật khẩu mặc định cho tất cả tài khoản mẫu: Password123!) ─────
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
    is_active = true;

-- ── 2. Course ──────────────────────────────────────────────────────────────
INSERT INTO courses (id, code, name, term, status, created_by)
VALUES (
    '00000000-0000-4000-8000-000000000002',
    'DACN-LOCAL',
    'Đồ án chuyên ngành Công nghệ phần mềm',
    'HK261',
    'active',
    '00000000-0000-4000-8000-000000000011'
)
ON CONFLICT (id) DO NOTHING;

-- ── 3. Course memberships (Giảng viên, TA, Sinh viên) ──────────────────────
INSERT INTO course_memberships (course_id, user_id, role)
VALUES
    ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000011', 'instructor'),
    ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000012', 'ta'),
    ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000001', 'student'),
    ('00000000-0000-4000-8000-000000000002', '00000000-0000-4000-8000-000000000013', 'student')
ON CONFLICT (course_id, user_id) DO NOTHING;

-- Tự động thêm các tài khoản đã đăng ký trên máy local vào khóa học với vai trò student
INSERT INTO course_memberships (course_id, user_id, role)
SELECT '00000000-0000-4000-8000-000000000002', u.id, 'student'
FROM users u
WHERE u.global_role IN ('user', 'student')
ON CONFLICT (course_id, user_id) DO NOTHING;

-- ── 4. Project (status = "open" — đã được giảng viên duyệt mở) ─────────────
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
SET status = 'open';

-- ── 5. Project groups ──────────────────────────────────────────────────────
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
ON CONFLICT (id) DO NOTHING;

-- ── 6. Group members ───────────────────────────────────────────────────────
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
ON CONFLICT (project_id, user_id) DO NOTHING;

-- Tự động thêm các tài khoản sinh viên/user đã đăng ký vào Local group để test nộp bài ngay
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
ON CONFLICT (project_id, user_id) DO NOTHING;

-- ── 7. Rubric version (status = "published") ───────────────────────────────
INSERT INTO rubric_versions (id, project_id, version_no, status, policy_version, published_at, created_by)
VALUES (
    '00000000-0000-4000-8000-000000000005',
    '00000000-0000-4000-8000-000000000003',
    1,
    'published',
    '1.0',
    NOW(),
    '00000000-0000-4000-8000-000000000011'
)
ON CONFLICT (id) DO NOTHING;

-- ── 8. Rubric criteria ─────────────────────────────────────────────────────
INSERT INTO rubric_criteria (
    id, rubric_version_id, code, title, description, weight, min_score, max_score, ordinal
)
VALUES
    (
        '00000000-0000-4000-8000-000000000021',
        '00000000-0000-4000-8000-000000000005',
        'C1',
        'Cấu trúc báo cáo & Trích dẫn học thuật',
        'Trình bày rõ ràng, đầy đủ căn cứ lý thuyết và trích dẫn tài liệu tham khảo chính xác.',
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
        'Thiết kế kiến trúc hợp lý, hiện thực mã nguồn khớp với các tuyên bố kỹ thuật trong báo cáo.',
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
ON CONFLICT (id) DO NOTHING;

COMMIT;
