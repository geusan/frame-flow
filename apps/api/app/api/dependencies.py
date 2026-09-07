from functools import lru_cache

from ..contexts.artifacts.application import ArtifactApplication
from ..contexts.administration.application import AdministrationApplication
from ..contexts.canvases.application import CanvasApplication
from ..contexts.formats.application import FormatApplication
from ..contexts.generation.application import GenerationApplication
from ..contexts.runs.application import RunApplication
from ..contexts.references.application import ReferenceApplication
from ..contexts.workflows.application import WorkflowApplication
from ..domain import utc_now
from ..infrastructure.persistence import (
    LegacySqlAlchemyArtifactOperations,
    LegacySqlAlchemyFormatOperations,
    LegacySqlAlchemyGenerationOperations,
    LegacySqlAlchemyWorkflowOperations,
    LegacySqlAlchemyRunOperations,
    LegacySqlAlchemyReferenceOperations,
    SqlAlchemyCanvasUnitOfWork,
    SqlAlchemyAdministrationOperations,
)
from ..service import new_id


@lru_cache(maxsize=1)
def get_canvas_application() -> CanvasApplication:
    return CanvasApplication(
        uow_factory=SqlAlchemyCanvasUnitOfWork,
        id_generator=new_id,
        clock=utc_now,
    )


@lru_cache(maxsize=1)
def get_administration_application() -> AdministrationApplication:
    return AdministrationApplication(SqlAlchemyAdministrationOperations())


@lru_cache(maxsize=1)
def get_artifact_application() -> ArtifactApplication:
    return ArtifactApplication(LegacySqlAlchemyArtifactOperations())


@lru_cache(maxsize=1)
def get_format_application() -> FormatApplication:
    return FormatApplication(LegacySqlAlchemyFormatOperations())


@lru_cache(maxsize=1)
def get_generation_application() -> GenerationApplication:
    return GenerationApplication(LegacySqlAlchemyGenerationOperations())


@lru_cache(maxsize=1)
def get_workflow_application() -> WorkflowApplication:
    return WorkflowApplication(LegacySqlAlchemyWorkflowOperations())


@lru_cache(maxsize=1)
def get_run_application() -> RunApplication:
    return RunApplication(LegacySqlAlchemyRunOperations())


@lru_cache(maxsize=1)
def get_reference_application() -> ReferenceApplication:
    return ReferenceApplication(LegacySqlAlchemyReferenceOperations())
