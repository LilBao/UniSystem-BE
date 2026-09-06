BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text NOT NULL UNIQUE,
  display_name text NOT NULL,
  global_role text NOT NULL DEFAULT 'user' CHECK (global_role IN ('user','admin')),
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE courses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code text NOT NULL,
  name text NOT NULL,
  term text NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','archived')),
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (code, term)
);

CREATE TABLE course_memberships (
  course_id uuid NOT NULL REFERENCES courses(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role text NOT NULL CHECK (role IN ('instructor','ta','student','reviewer')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (course_id, user_id)
);

CREATE TABLE projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id uuid NOT NULL UNIQUE REFERENCES courses(id),
  title text NOT NULL,
  description text,
  due_at timestamptz,
  max_score numeric(8,3) NOT NULL DEFAULT 10 CHECK (max_score > 0),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','open','closed','archived')),
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE project_groups (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  name text NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','locked','archived')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  UNIQUE (id, project_id),
  UNIQUE (project_id, name)
);

CREATE TABLE group_members (
  group_id uuid NOT NULL,
  project_id uuid NOT NULL REFERENCES projects(id),
  user_id uuid NOT NULL REFERENCES users(id),
  role text NOT NULL DEFAULT 'member' CHECK (role IN ('leader','member')),
  joined_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (group_id, user_id),
  FOREIGN KEY (group_id, project_id) REFERENCES project_groups(id, project_id),
  UNIQUE (project_id, user_id)
);

CREATE TABLE rubric_versions (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  version_no integer NOT NULL CHECK (version_no > 0),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
  policy_version text NOT NULL,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  published_at timestamptz,
  created_by uuid NOT NULL REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id),
  UNIQUE (id, project_id),
  UNIQUE (project_id, version_no),
  CHECK (status <> 'published' OR published_at IS NOT NULL)
);

CREATE TABLE submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id),
  group_id uuid NOT NULL,
  submitted_by_user_id uuid NOT NULL REFERENCES users(id),
  rubric_version_id uuid NOT NULL,
  attempt_no integer NOT NULL DEFAULT 1 CHECK (attempt_no > 0),
  idempotency_key text,
  status text NOT NULL DEFAULT 'uploaded' CHECK (status IN (
    'uploaded','validating','processing','requires_review','completed','failed','archived'
  )),
  submitted_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (group_id, project_id) REFERENCES project_groups(id, project_id),
  FOREIGN KEY (group_id, submitted_by_user_id) REFERENCES group_members(group_id, user_id),
  FOREIGN KEY (rubric_version_id, project_id) REFERENCES rubric_versions(id, project_id),
  UNIQUE (project_id, group_id, attempt_no)
);
CREATE UNIQUE INDEX uq_submissions_idempotency_key
  ON submissions(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid REFERENCES submissions(id),
  kind text NOT NULL CHECK (kind IN (
    'report_pdf','rubric_pdf','source_archive','reference_pdf','parsed_json',
    'parsed_markdown','figure','table','equation','code_graph','sandbox_log',
    'annotated_pdf','other'
  )),
  version_no integer NOT NULL DEFAULT 1 CHECK (version_no > 0),
  object_uri text NOT NULL,
  media_type text NOT NULL,
  byte_size bigint NOT NULL CHECK (byte_size >= 0),
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (object_uri, version_no),
  UNIQUE (submission_id, kind, version_no, sha256)
);

CREATE TABLE rubric_sources (
  rubric_version_id uuid PRIMARY KEY REFERENCES rubric_versions(id),
  artifact_id uuid NOT NULL UNIQUE REFERENCES artifacts(id),
  parse_status text NOT NULL DEFAULT 'pending' CHECK (
    parse_status IN ('pending','processing','parsed','failed','verified')
  ),
  parser_version text,
  parsed_at timestamptz,
  verified_by uuid REFERENCES users(id),
  verified_at timestamptz,
  parse_error jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE rubric_criteria (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rubric_version_id uuid NOT NULL REFERENCES rubric_versions(id),
  parent_id uuid REFERENCES rubric_criteria(id),
  code text NOT NULL,
  title text NOT NULL,
  description text NOT NULL,
  weight numeric(8,6) NOT NULL CHECK (weight BETWEEN 0 AND 1),
  min_score numeric(8,3) NOT NULL DEFAULT 0,
  max_score numeric(8,3) NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  source_page integer CHECK (source_page IS NULL OR source_page > 0),
  source_bbox jsonb,
  source_text text,
  grading_rules jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (rubric_version_id, code),
  UNIQUE (rubric_version_id, ordinal),
  CHECK (max_score > min_score)
);

CREATE TABLE document_sections (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL REFERENCES artifacts(id),
  parent_id uuid REFERENCES document_sections(id),
  title text,
  level integer NOT NULL DEFAULT 1 CHECK (level > 0),
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  page_start integer NOT NULL CHECK (page_start > 0),
  page_end integer NOT NULL,
  section_path text[] NOT NULL DEFAULT ARRAY[]::text[],
  UNIQUE (artifact_id, ordinal),
  CHECK (page_end >= page_start)
);

CREATE TABLE document_blocks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL REFERENCES artifacts(id),
  section_id uuid REFERENCES document_sections(id),
  parent_block_id uuid REFERENCES document_blocks(id),
  caption_block_id uuid REFERENCES document_blocks(id),
  block_type text NOT NULL CHECK (block_type IN (
    'text','title','list','table','figure','equation','caption','citation',
    'header','footer','other'
  )),
  page_no integer NOT NULL CHECK (page_no > 0),
  reading_order integer NOT NULL CHECK (reading_order >= 0),
  text_content text,
  bbox jsonb NOT NULL,
  quads jsonb NOT NULL DEFAULT '[]'::jsonb,
  citation_marker_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
  confidence numeric(5,4) CHECK (confidence BETWEEN 0 AND 1),
  parser_version text NOT NULL,
  source_locator jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (artifact_id, page_no, reading_order)
);

CREATE TABLE reference_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id uuid REFERENCES courses(id),
  source_kind text NOT NULL CHECK (source_kind IN (
    'paper','book','web','dataset','student_attachment','other'
  )),
  visibility text NOT NULL DEFAULT 'global' CHECK (visibility IN ('global','course','private')),
  title text NOT NULL,
  authors jsonb NOT NULL DEFAULT '[]'::jsonb,
  publication_year integer,
  doi text,
  canonical_url text,
  artifact_id uuid REFERENCES artifacts(id),
  language text,
  access_status text NOT NULL DEFAULT 'metadata_only' CHECK (
    access_status IN ('metadata_only','abstract','full_text','unavailable')
  ),
  content_sha256 text CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((visibility <> 'course') OR tenant_id IS NOT NULL)
);

CREATE TABLE reference_passages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  reference_document_id uuid NOT NULL REFERENCES reference_documents(id),
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  content text NOT NULL,
  token_count integer CHECK (token_count IS NULL OR token_count >= 0),
  section_path text[] NOT NULL DEFAULT ARRAY[]::text[],
  page_start integer CHECK (page_start IS NULL OR page_start > 0),
  page_end integer NOT NULL,
  block_type text NOT NULL DEFAULT 'text' CHECK (
    block_type IN ('text','table','figure','equation','abstract','caption')
  ),
  access_level text NOT NULL DEFAULT 'full_text' CHECK (access_level IN ('abstract','full_text')),
  content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  chunker_version text NOT NULL,
  is_active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (reference_document_id, ordinal, chunker_version),
  CHECK (page_end IS NULL OR (page_start IS NOT NULL AND page_end >= page_start))
);

CREATE TABLE submission_references (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES submissions(id),
  marker text NOT NULL,
  raw_citation text NOT NULL,
  reference_document_id uuid REFERENCES reference_documents(id),
  resolver_status text NOT NULL DEFAULT 'unresolved' CHECK (
    resolver_status IN ('unresolved','resolved','ambiguous','not_found')
  ),
  resolver_confidence numeric(5,4) CHECK (resolver_confidence BETWEEN 0 AND 1),
  resolver_version text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (submission_id, marker)
);

CREATE TABLE claims (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES submissions(id),
  source_block_id uuid REFERENCES document_blocks(id),
  claim_type text NOT NULL CHECK (
    claim_type IN ('text','citation','factual','implementation','evaluative')
  ),
  text_content text NOT NULL,
  is_atomic boolean NOT NULL DEFAULT true,
  is_central boolean NOT NULL DEFAULT false,
  qualifiers jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_span jsonb NOT NULL,
  context_block_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
  impact smallint NOT NULL DEFAULT 1 CHECK (impact BETWEEN 0 AND 3),
  testability smallint NOT NULL DEFAULT 0 CHECK (testability BETWEEN 0 AND 3),
  risk smallint NOT NULL DEFAULT 1 CHECK (risk BETWEEN 0 AND 3),
  extractor_version text NOT NULL,
  confidence numeric(5,4) CHECK (confidence BETWEEN 0 AND 1),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE claim_references (
  claim_id uuid NOT NULL REFERENCES claims(id),
  submission_reference_id uuid NOT NULL REFERENCES submission_references(id),
  PRIMARY KEY (claim_id, submission_reference_id)
);

CREATE TABLE code_graph_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES submissions(id),
  source_artifact_id uuid NOT NULL REFERENCES artifacts(id),
  graph_artifact_id uuid NOT NULL REFERENCES artifacts(id),
  source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
  graphify_version text NOT NULL,
  schema_version text NOT NULL,
  node_count integer CHECK (node_count IS NULL OR node_count >= 0),
  edge_count integer CHECK (edge_count IS NULL OR edge_count >= 0),
  provenance_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (submission_id, source_sha256, graphify_version)
);

CREATE TABLE pipeline_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES submissions(id),
  pipeline text NOT NULL CHECK (pipeline IN ('L1','P1','P2','P3','P4','L3')),
  status text NOT NULL DEFAULT 'queued' CHECK (status IN (
    'queued','running','succeeded','partial','abstained','requires_review','failed','cancelled'
  )),
  attempt_no integer NOT NULL DEFAULT 1 CHECK (attempt_no > 0),
  code_version text NOT NULL,
  model_version text,
  prompt_version text,
  schema_version text NOT NULL,
  policy_version text NOT NULL,
  random_seed bigint,
  input_fingerprint text NOT NULL,
  output_fingerprint text,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  cost jsonb NOT NULL DEFAULT '{}'::jsonb,
  error jsonb,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (submission_id, pipeline, input_fingerprint, attempt_no)
);

CREATE TABLE pipeline_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_run_id uuid NOT NULL REFERENCES pipeline_runs(id),
  subject_type text NOT NULL CHECK (subject_type IN (
    'submission','criterion','claim','segment','citation','code_claim'
  )),
  subject_id uuid,
  status text NOT NULL CHECK (status IN (
    'succeeded','partial','abstained','requires_review','failed'
  )),
  verdict text,
  confidence numeric(5,4) CHECK (confidence BETWEEN 0 AND 1),
  reason_codes text[] NOT NULL DEFAULT ARRAY[]::text[],
  escalation_history jsonb NOT NULL DEFAULT '[]'::jsonb,
  result jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence_packs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL REFERENCES submissions(id),
  claim_id uuid REFERENCES claims(id),
  rubric_criterion_id uuid REFERENCES rubric_criteria(id),
  pipeline_run_id uuid NOT NULL REFERENCES pipeline_runs(id),
  coverage jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (claim_id IS NOT NULL OR rubric_criterion_id IS NOT NULL)
);

CREATE TABLE evidence_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_pack_id uuid NOT NULL REFERENCES evidence_packs(id),
  source_type text NOT NULL CHECK (source_type IN (
    'submission_block','reference_passage','code_node','code_edge',
    'execution_log','human_note','other'
  )),
  source_id uuid,
  source_uri text,
  text_snapshot text,
  location jsonb NOT NULL DEFAULT '{}'::jsonb,
  provenance text NOT NULL CHECK (provenance IN (
    'parsed','retrieved','reranked','extracted','inferred','ambiguous','executed','human'
  )),
  retrieval_score double precision,
  rerank_score double precision,
  supports_atoms text[] NOT NULL DEFAULT ARRAY[]::text[],
  contradicts_atoms text[] NOT NULL DEFAULT ARRAY[]::text[],
  access_status text,
  content_sha256 text CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pipeline_result_evidence (
  pipeline_result_id uuid NOT NULL REFERENCES pipeline_results(id),
  evidence_item_id uuid NOT NULL REFERENCES evidence_items(id),
  usage text NOT NULL DEFAULT 'support' CHECK (usage IN ('support','contradict','context')),
  PRIMARY KEY (pipeline_result_id, evidence_item_id)
);

CREATE TABLE rubric_criterion_scores (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_result_id uuid NOT NULL REFERENCES pipeline_results(id),
  rubric_criterion_id uuid NOT NULL REFERENCES rubric_criteria(id),
  run_index integer NOT NULL DEFAULT 1 CHECK (run_index > 0),
  raw_score numeric(10,6) NOT NULL,
  normalized_score numeric(10,6) NOT NULL CHECK (normalized_score BETWEEN 0 AND 1),
  rationale text NOT NULL,
  variance numeric(12,8) CHECK (variance IS NULL OR variance >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pipeline_result_id, rubric_criterion_id, run_index)
);

CREATE TABLE citation_verdicts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_result_id uuid NOT NULL UNIQUE REFERENCES pipeline_results(id),
  claim_id uuid NOT NULL REFERENCES claims(id),
  verdict text NOT NULL CHECK (verdict IN ('SUPPORT','REFUTE','NEI')),
  confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  pair_accuracy_label boolean,
  requires_review boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE code_consistency_verdicts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_result_id uuid NOT NULL UNIQUE REFERENCES pipeline_results(id),
  claim_id uuid NOT NULL REFERENCES claims(id),
  graph_snapshot_id uuid REFERENCES code_graph_snapshots(id),
  verdict text NOT NULL CHECK (verdict IN (
    'CONSISTENT','INCONSISTENT','AMBIGUOUS','NOT_TESTABLE','NEI'
  )),
  verification_stage text NOT NULL CHECK (verification_stage IN (
    'EXTRACTED','LLM_JUDGE','EXECUTION'
  )),
  confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  requires_review boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai_signals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  pipeline_result_id uuid NOT NULL UNIQUE REFERENCES pipeline_results(id),
  submission_id uuid NOT NULL REFERENCES submissions(id),
  language text NOT NULL,
  domain text NOT NULL,
  raw_score double precision NOT NULL,
  level text NOT NULL CHECK (level IN ('low','moderate','high')),
  confidence numeric(5,4) NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  uncertainty numeric(5,4) CHECK (uncertainty BETWEEN 0 AND 1),
  threshold_profile text NOT NULL,
  detector_version text NOT NULL,
  stylometric_signals jsonb NOT NULL DEFAULT '{}'::jsonb,
  segment_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
  requires_review boolean NOT NULL DEFAULT false,
  academic_score_effect numeric(8,3) NOT NULL DEFAULT 0 CHECK (academic_score_effect = 0),
  disclaimer text NOT NULL DEFAULT 'Review-only evidence signal; not a misconduct verdict.',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE final_evaluations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  submission_id uuid NOT NULL UNIQUE REFERENCES submissions(id),
  rubric_version_id uuid NOT NULL REFERENCES rubric_versions(id),
  policy_version text NOT NULL,
  status text NOT NULL DEFAULT 'draft' CHECK (status IN (
    'draft','requires_review','published','superseded'
  )),
  academic_score numeric(10,4),
  max_score numeric(10,4) NOT NULL CHECK (max_score > 0),
  score_breakdown jsonb NOT NULL DEFAULT '{}'::jsonb,
  citation_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  consistency_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  integrity_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  explanation text,
  evidence_coverage numeric(5,4) CHECK (evidence_coverage BETWEEN 0 AND 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  CHECK (academic_score IS NULL OR academic_score BETWEEN 0 AND max_score)
);

CREATE TABLE feedback_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  final_evaluation_id uuid NOT NULL REFERENCES final_evaluations(id),
  audience text NOT NULL CHECK (audience IN ('student','instructor','both')),
  category text NOT NULL CHECK (category IN (
    'rubric','citation','code_consistency','integrity','presentation','other'
  )),
  severity text NOT NULL CHECK (severity IN ('info','warning','critical')),
  message text NOT NULL,
  why_it_matters text,
  suggestion text,
  claim_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
  evidence_item_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
  ordinal integer NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE human_overrides (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  final_evaluation_id uuid NOT NULL REFERENCES final_evaluations(id),
  actor_id uuid NOT NULL REFERENCES users(id),
  target_type text NOT NULL CHECK (target_type IN (
    'criterion_score','citation_verdict','consistency_verdict',
    'feedback','final_score','review_status'
  )),
  target_id uuid,
  before_value jsonb NOT NULL,
  after_value jsonb NOT NULL,
  reason text NOT NULL CHECK (length(trim(reason)) > 0),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  actor_type text NOT NULL DEFAULT 'system' CHECK (actor_type IN ('user','service','system')),
  actor_user_id uuid REFERENCES users(id),
  actor_service text,
  course_id uuid REFERENCES courses(id),
  submission_id uuid REFERENCES submissions(id),
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id text,
  outcome text NOT NULL DEFAULT 'success' CHECK (outcome IN ('success','failure','denied')),
  request_id text,
  correlation_id text,
  trace_id text,
  source text NOT NULL DEFAULT 'db_trigger' CHECK (source IN ('api','worker','db_trigger','admin','system')),
  source_service text,
  http_method text,
  request_path text,
  http_status integer CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
  ip_address inet,
  user_agent text,
  changed_fields text[] NOT NULL DEFAULT ARRAY[]::text[],
  before_data jsonb,
  after_data jsonb,
  reason text,
  error_code text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  CHECK ((actor_type <> 'user') OR actor_user_id IS NOT NULL),
  CHECK ((actor_type = 'user') OR actor_service IS NOT NULL OR actor_type = 'system')
);

CREATE TABLE highlights (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  feedback_item_id uuid NOT NULL REFERENCES feedback_items(id),
  artifact_id uuid NOT NULL REFERENCES artifacts(id),
  page_no integer NOT NULL CHECK (page_no > 0),
  quads jsonb NOT NULL,
  color text NOT NULL DEFAULT '#F6C85F',
  tooltip text,
  visibility text NOT NULL DEFAULT 'student' CHECK (visibility IN ('student','instructor','both')),
  annotation_status text NOT NULL DEFAULT 'draft' CHECK (
    annotation_status IN ('draft','confirmed','exported','rejected')
  ),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_immutable
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();

CREATE TRIGGER users_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER courses_updated_at BEFORE UPDATE ON courses
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER projects_updated_at BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER project_groups_updated_at BEFORE UPDATE ON project_groups
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER submissions_updated_at BEFORE UPDATE ON submissions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER reference_documents_updated_at BEFORE UPDATE ON reference_documents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER reference_passages_updated_at BEFORE UPDATE ON reference_passages
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_course_memberships_user ON course_memberships(user_id);
CREATE INDEX idx_group_members_user ON group_members(user_id);
CREATE INDEX idx_submissions_group ON submissions(group_id, submitted_at DESC);
CREATE INDEX idx_artifacts_submission ON artifacts(submission_id, kind, version_no DESC);
CREATE INDEX idx_document_blocks_artifact_page ON document_blocks(artifact_id, page_no, reading_order);
CREATE INDEX idx_claims_submission ON claims(submission_id);
CREATE INDEX idx_pipeline_runs_submission ON pipeline_runs(submission_id, created_at DESC);
CREATE INDEX idx_pipeline_results_run ON pipeline_results(pipeline_run_id);
CREATE INDEX idx_audit_course_time ON audit_logs(course_id, occurred_at DESC);
CREATE INDEX idx_audit_submission_time ON audit_logs(submission_id, occurred_at DESC);
CREATE INDEX idx_highlights_artifact_page ON highlights(artifact_id, page_no);

COMMIT;
