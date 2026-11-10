"""Voice endpoints: transcription, voice commands and optional text-to-speech."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Header, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.dependencies import OperatorDep, RunServiceDep, ViewerDep, VoiceServiceDep
from app.schemas.run import RunCreate, RunDetail

router = APIRouter(prefix="/voice", tags=["voice"])


class TranscriptResponse(BaseModel):
    text: str


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.get("/capabilities")
async def voice_capabilities(service: VoiceServiceDep, _: ViewerDep) -> dict[str, str | None]:
    return service.capabilities


@router.post("/transcribe", response_model=TranscriptResponse)
async def transcribe(
    service: VoiceServiceDep, _: OperatorDep, audio: Annotated[UploadFile, File()]
) -> TranscriptResponse:
    text = await service.transcribe(await audio.read(), audio.content_type or "")
    return TranscriptResponse(text=text)


@router.post("/command", response_model=RunDetail, status_code=status.HTTP_202_ACCEPTED)
async def voice_command(
    voice: VoiceServiceDep,
    runs: RunServiceDep,
    principal: OperatorDep,
    audio: Annotated[UploadFile, File()],
    connection_id: Annotated[str, Form()],
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
) -> RunDetail:
    text = await voice.transcribe(await audio.read(), audio.content_type or "")
    return await runs.create(
        principal,
        RunCreate(connection_id=connection_id, text=text, input_mode="voice"),
        idempotency_key,
    )


@router.post("/speak")
async def speak(payload: SpeakRequest, service: VoiceServiceDep, _: ViewerDep) -> Response:
    audio = await service.speak(payload.text)
    return Response(content=audio.content, media_type=audio.media_type)
