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

-- ── 8. Rubric Criteria (Tiêu chí chấm điểm đề tài đồ án) ─────────────────────
INSERT INTO rubric_criteria (id, rubric_version_id, code, title, description, weight, min_score, max_score, ordinal, grading_rules)
VALUES
(
    '00000000-0000-4000-8000-000000000011',
    '00000000-0000-4000-8000-000000000005',
    'CRIT-1',
    'Đặt vấn đề & Mục tiêu đề tài',
    'Đánh giá tính cấp thiết, rõ ràng của mục tiêu nghiên cứu và phạm vi đề tài đồ án.',
    0.20,
    0.0,
    10.0,
    1,
    '{"excellent": "Mục tiêu cụ thể, tính cấp thiết rõ ràng, phạm vi khả thi", "poor": "Mơ hồ, thiếu động lực nghiên cứu"}'::jsonb
),
(
    '00000000-0000-4000-8000-000000000012',
    '00000000-0000-4000-8000-000000000005',
    'CRIT-2',
    'Tổng quan tài liệu & Cơ sở lý thuyết',
    'Khảo sát các công trình liên quan, phân tích điểm mạnh/yếu của các giải pháp hiện có.',
    0.20,
    0.0,
    10.0,
    2,
    '{"excellent": "Khảo sát sâu rộng, trích dẫn bài báo uy tín, chỉ ra research gap", "poor": "Thiếu trích dẫn hoặc lạc hậu"}'::jsonb
),
(
    '00000000-0000-4000-8000-000000000013',
    '00000000-0000-4000-8000-000000000005',
    'CRIT-3',
    'Kiến trúc hệ thống & Phương pháp giải quyết',
    'Mô tả chi tiết giải pháp đề xuất, thiết kế kiến trúc, thuật toán và luồng xử lý.',
    0.30,
    0.0,
    10.0,
    3,
    '{"excellent": "Kiến trúc rõ ràng, thiết kế mạch lạc, phương pháp chặt chẽ", "poor": "Thiết kế chắp vá, thiếu sơ đồ minh họa"}'::jsonb
),
(
    '00000000-0000-4000-8000-000000000014',
    '00000000-0000-4000-8000-000000000005',
    'CRIT-4',
    'Hiện thực hóa & Đánh giá thực nghiệm',
    'Chất lượng triển khai mã nguồn, kết quả thử nghiệm và so sánh với baseline.',
    0.20,
    0.0,
    10.0,
    4,
    '{"excellent": "Có thực nghiệm so sánh đầy đủ, phân tích số liệu chi tiết", "poor": "Không có thực nghiệm hoặc số liệu sơ sài"}'::jsonb
),
(
    '00000000-0000-4000-8000-000000000015',
    '00000000-0000-4000-8000-000000000005',
    'CRIT-5',
    'Trình bày & Văn phong học thuật',
    'Định dạng văn bản, hình vẽ, bảng biểu, công thức toán và quy chuẩn trích dẫn.',
    0.10,
    0.0,
    10.0,
    5,
    '{"excellent": "Đúng chuẩn học thuật, bảng biểu/hình vẽ chú thích rõ ràng", "poor": "Nhiều lỗi chính tả, format lộn xộn"}'::jsonb
)
ON CONFLICT DO NOTHING;

COMMIT;
