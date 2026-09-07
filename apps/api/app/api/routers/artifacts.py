from __future__ import annotations

import json
import re
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.responses import RedirectResponse

from ...contexts.artifacts.application import (
    ArtifactApplication,
    CaptureFrameCommand,
    ImportArtifactUrlCommand,
    SaveImageEditCommand,
    SceneSearchCommand,
    TrainCharacterLoraCommand,
    UploadArtifactCommand,
)
from ...contexts.artifacts.domain import (
    CANVAS_ARTIFACT_MAX_BYTES,
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactPayloadTooLargeError,
    ArtifactServiceUnavailableError,
    ArtifactUnsupportedMediaError,
    ArtifactValidationError,
)
from ...domain import (
    ArtifactResponse,
    ArtifactUrlImportRequest,
    CharacterLoraTrainRequest,
    FrameCaptureRequest,
    ImageEditDocument,
    SceneSearchRequest,
    SignedUrlRequest,
)
from ..dependencies import get_artifact_application


router = APIRouter(tags=["artifacts"])


def _raise_artifact_http_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ArtifactNotFoundError):
        raise HTTPException(404, str(exc)) from exc
    if isinstance(exc, ArtifactConflictError):
        raise HTTPException(409, str(exc)) from exc
    if isinstance(exc, ArtifactUnsupportedMediaError):
        raise HTTPException(415, str(exc)) from exc
    if isinstance(exc, ArtifactPayloadTooLargeError):
        raise HTTPException(413, str(exc)) from exc
    if isinstance(exc, ArtifactServiceUnavailableError):
        raise HTTPException(503, str(exc)) from exc
    if isinstance(exc, ArtifactValidationError):
        raise HTTPException(422, str(exc)) from exc
    raise exc


ARTIFACT_ERRORS = (
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactPayloadTooLargeError,
    ArtifactServiceUnavailableError,
    ArtifactUnsupportedMediaError,
    ArtifactValidationError,
)


@router.get("/artifacts")
def list_artifacts(
    types: str = Query(default="Image,Video,Audio,Text,FinalVideo"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    application: ArtifactApplication = Depends(get_artifact_application),
) -> list[dict[str, Any]]:
    return application.list_artifacts(types, limit, offset)


@router.get("/characters")
def list_characters(
    application: ArtifactApplication = Depends(get_artifact_application),
) -> list[dict[str, Any]]:
    return application.list_characters()


@router.post(
    "/characters/{character_id}/lora-training",
    status_code=status.HTTP_202_ACCEPTED,
)
def start_character_lora_training(
    character_id: str,
    payload: CharacterLoraTrainRequest,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    try:
        return application.start_character_lora(
            TrainCharacterLoraCommand(
                character_id=character_id,
                trigger_word=payload.trigger_word,
                steps=payload.steps,
                learning_rate=payload.learning_rate,
            )
        )
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.get("/characters/{character_id}/lora-training")
def get_character_lora_training(
    character_id: str,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    try:
        return application.get_character_lora(character_id)
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: str,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> ArtifactResponse:
    try:
        return application.get_artifact(artifact_id)
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.post(
    "/artifacts/{artifact_id}/audio-asset",
    status_code=status.HTTP_201_CREATED,
)
def create_audio_asset_from_reference(
    artifact_id: str,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    try:
        return application.create_audio_asset(artifact_id)
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.get("/artifacts/{artifact_id}/lineage")
def get_artifact_lineage(
    artifact_id: str,
    direction: Literal["ancestors", "descendants", "both"] = Query(default="both"),
    depth: int = Query(default=8, ge=0, le=32),
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, object]:
    try:
        return application.get_lineage(artifact_id, direction, depth)
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.post("/artifacts/{artifact_id}/scene-search")
def search_artifact_scenes(
    artifact_id: str,
    payload: SceneSearchRequest,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, object]:
    try:
        return application.search_scenes(
            SceneSearchCommand(
                artifact_id=artifact_id,
                values=payload.model_dump(mode="python"),
            )
        )
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.post(
    "/artifacts/{artifact_id}/capture-frame",
    status_code=status.HTTP_201_CREATED,
)
def capture_artifact_frame(
    artifact_id: str,
    payload: FrameCaptureRequest,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    try:
        return application.capture_frame(
            CaptureFrameCommand(
                artifact_id=artifact_id,
                values=payload.model_dump(mode="python"),
            )
        )
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.get("/artifacts/{artifact_id}/frame-preview")
def preview_artifact_frame(
    artifact_id: str,
    timestamp_ms: int = Query(ge=0),
    application: ArtifactApplication = Depends(get_artifact_application),
) -> Response:
    try:
        content = application.preview_frame(artifact_id, timestamp_ms)
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)
    return Response(
        content=content.data,
        media_type=content.content_type,
        headers=content.headers,
    )


@router.post("/artifacts/upload-url")
def artifact_upload_url(
    payload: SignedUrlRequest,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    try:
        return application.create_upload_target(payload.filename, payload.content_type)
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.post("/artifacts/import-url", status_code=status.HTTP_201_CREATED)
def import_artifact_url(
    payload: ArtifactUrlImportRequest,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    try:
        return application.import_url(ImportArtifactUrlCommand(url=str(payload.url)))
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.post("/artifacts/upload", status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    file: UploadFile = File(...),
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    content = await file.read(CANVAS_ARTIFACT_MAX_BYTES + 1)
    try:
        return application.upload(
            UploadArtifactCommand(
                filename=file.filename or "upload.bin",
                content_type=file.content_type or "application/octet-stream",
                content=content,
            )
        )
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.post(
    "/artifacts/{artifact_id}/image-edits",
    status_code=status.HTTP_201_CREATED,
)
async def save_manual_image_edit(
    artifact_id: str,
    file: UploadFile = File(...),
    edit_document: str = Form(...),
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    if len(edit_document.encode()) > 32_000:
        raise HTTPException(413, "image edit document is too large")
    try:
        document = ImageEditDocument.model_validate(json.loads(edit_document))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, f"invalid image edit document: {exc}") from exc
    content = await file.read(CANVAS_ARTIFACT_MAX_BYTES + 1)
    try:
        return application.save_image_edit(
            SaveImageEditCommand(
                artifact_id=artifact_id,
                filename=file.filename or "edit.png",
                content_type=file.content_type or "application/octet-stream",
                content=content,
                document=document.model_dump(exclude_none=True),
            )
        )
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.get("/artifacts/{artifact_id}/download-url")
def artifact_download_url(
    artifact_id: str,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> dict[str, Any]:
    try:
        return application.create_download_url(artifact_id)
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(
    artifact_id: str,
    request: Request,
    application: ArtifactApplication = Depends(get_artifact_application),
) -> Response:
    try:
        stored = application.get_content(artifact_id)
    except ARTIFACT_ERRORS as exc:
        _raise_artifact_http_error(exc)
    if stored.redirect_url is not None:
        return RedirectResponse(stored.redirect_url, status_code=307)
    content = stored.data or b""
    range_header = request.headers.get("range")
    if not range_header:
        return Response(
            content,
            media_type=stored.content_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(content)),
            },
        )
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
    if not match or not any(match.groups()):
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{len(content)}"},
        )
    start_text, end_text = match.groups()
    if start_text:
        start = int(start_text)
        end = (
            min(int(end_text), len(content) - 1)
            if end_text
            else len(content) - 1
        )
    else:
        suffix_length = int(end_text)
        start = max(0, len(content) - suffix_length)
        end = len(content) - 1
    if start >= len(content) or end < start:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{len(content)}"},
        )
    partial = content[start : end + 1]
    return Response(
        partial,
        status_code=206,
        media_type=stored.content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Range": f"bytes {start}-{end}/{len(content)}",
            "Content-Length": str(len(partial)),
        },
    )
