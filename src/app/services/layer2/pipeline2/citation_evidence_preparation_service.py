from app.services.layer2.pipeline2.citation_verification_service import CitationVerificationService


class CitationEvidencePreparationService(CitationVerificationService):
    """Compatibility name for callers that previously imported the preparation service.

    Pipeline 2 now verifies citations through ``CitationVerificationService``; this alias
    remains so downstream code has a non-breaking migration path.
    """
