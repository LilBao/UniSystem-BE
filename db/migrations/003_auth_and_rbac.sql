BEGIN;

ALTER TABLE users
ADD COLUMN IF NOT EXISTS password_hash text;

ALTER TABLE users
DROP CONSTRAINT IF EXISTS users_global_role_check,
DROP CONSTRAINT IF EXISTS ck_users_global_role;

ALTER TABLE users
ADD CONSTRAINT ck_users_global_role
CHECK (global_role IN ('user', 'student', 'instructor', 'admin'));

CREATE UNIQUE INDEX IF NOT EXISTS uq_users_normalized_email
ON users (lower(email));

COMMIT;
