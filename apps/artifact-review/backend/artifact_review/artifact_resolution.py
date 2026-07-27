"""Map artifact ids and static urls to staged artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from artifact_review import artifact_paths
from artifact_review.feedback_database import ensure_feedback_schema
from artifact_review.models import ArtifactIndex


@dataclass(frozen=True)
class ArtifactSummary:
    """A staged artifact listed for the SPA index."""

    project: str
    subdir: str
    artifact_id: str
    last_pushed: int
    entry_count: int


def artifact_id_for(project: str, subdir: str) -> str:
    """Return the stable artifact id for a staged project/subdir."""
    artifact_paths.validate_name(project)
    artifact_paths.validate_name(subdir)
    ensure_feedback_schema()
    row = ArtifactIndex.objects.filter(project=project, subdir=subdir).first()
    if row is not None:
        return row.artifact_id
    return f"{project}/{subdir}"


def resolve(artifact_id: str) -> tuple[str, str]:
    """Resolve an artifact id to its staged project/subdir."""
    ensure_feedback_schema()
    row = ArtifactIndex.objects.filter(artifact_id=artifact_id).order_by("-last_pushed").first()
    if row is not None:
        return row.project, row.subdir
    project, separator, subdir = artifact_id.partition("/")
    if not separator:
        raise ValueError("unknown_artifact")
    artifact_paths.validate_name(project)
    artifact_paths.validate_name(subdir)
    return project, subdir


def list_artifacts() -> list[ArtifactSummary]:
    """Return staged artifact summaries for the SPA index."""
    ensure_feedback_schema()
    summaries: list[ArtifactSummary] = []
    for row in ArtifactIndex.objects.order_by("project", "subdir"):
        artifact_path = artifact_paths.safe_join(artifact_paths.stage_root(), f"{row.project}/{row.subdir}")
        entry_count = _entry_count(artifact_path)
        summaries.append(
            ArtifactSummary(
                project=row.project,
                subdir=row.subdir,
                artifact_id=row.artifact_id,
                last_pushed=row.last_pushed,
                entry_count=entry_count,
            )
        )
    return summaries


def _entry_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for child in path.rglob("*") if child.is_file())


__all__ = ["ArtifactSummary", "artifact_id_for", "list_artifacts", "resolve"]
