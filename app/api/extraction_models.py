"""Frontend-facing extraction job contract, also published through OpenAPI."""
from typing import Literal

from pydantic import BaseModel, Field

from app.llm.extraction import ExtractedRequirements

JobStatus = Literal["queued", "selecting", "reading", "extracting", "completed", "failed"]
FieldStatus = Literal["extracted", "not_found", "conflict"]


class Progress(BaseModel):
    completed_chunks: int = 0
    total_chunks: int | None = None


class SourceFinding(BaseModel):
    file: str
    pages: list[int]
    value: str | float | list[str]


class SelectedDocument(BaseModel):
    id: int
    path: str
    title: str
    decision: Literal["include", "exclude"]
    relevant_fields: list[str]
    reason: str


class ExtractionResult(BaseModel):
    fields: ExtractedRequirements
    field_status: dict[str, FieldStatus]
    conflicts: dict[str, list[str | float]]
    aggregated_fields: dict[str, list[str]]
    evidence: dict[str, list[SourceFinding]]
    documents: list[SelectedDocument]
    ignored_non_pdf: list[str]
    requires_review: bool
    pages_processed: int
    chunks_processed: int
    coverage: Literal["selected_pdfs_only"] = "selected_pdfs_only"


class JobError(BaseModel):
    code: str
    message: str


class ExtractionJob(BaseModel):
    id: str
    filename: str
    model: str
    status: JobStatus = "queued"
    progress: Progress = Field(default_factory=Progress)
    result: ExtractionResult | None = None
    error: JobError | None = None


class JobAccepted(BaseModel):
    id: str
    status_url: str
    audit_url: str


def make_result(fields, audit, selection):
    evidence = {field: [] for field in type(fields).model_fields}
    for chunk in audit["chunks"]:
        for field, value in chunk["fields"].items():
            if value is not None and value != [] and value != "":
                finding = SourceFinding(file=chunk["file"], pages=chunk["source_pages"], value=value)
                if finding not in evidence[field]:
                    evidence[field].append(finding)
    return ExtractionResult(
        fields=fields, field_status=audit["field_status"], conflicts=audit["conflicts"],
        aggregated_fields=audit["aggregated_fields"], evidence=evidence,
        documents=[SelectedDocument.model_validate(entry) for entry in selection["pdfs"]],
        ignored_non_pdf=selection["ignored_non_pdf"], requires_review=audit["requires_review"],
        pages_processed=audit["pages_processed"], chunks_processed=audit["chunks_processed"],
    )
