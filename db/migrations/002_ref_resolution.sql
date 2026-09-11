BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS
uq_reference_documents_normalized_doi
ON reference_documents (lower(doi))
WHERE doi IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS
uq_reference_documents_canonical_url
ON reference_documents (canonical_url)
WHERE canonical_url IS NOT NULL;

CREATE INDEX IF NOT EXISTS
idx_submission_references_resolution
ON submission_references (
    submission_id,
    resolver_status
);

COMMIT;
