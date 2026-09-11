"""DDS download endpoints: the JSON dossier and the EUDR SOAP XML."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from terrasentry_api.services import get_session
from terrasentry_api.store import RunStore

router = APIRouter(prefix="/dds", tags=["dds"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{run_id}")
async def get_dds(run_id: str, session: SessionDep) -> dict[str, Any]:
    store = RunStore(session)
    dds = await store.get_dds(run_id)
    if dds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"run {run_id!r} has no DDS")
    if not dds.released:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run {run_id!r} is awaiting review; the DDS is withheld",
        )
    return dds.document


@router.get("/{run_id}/xml")
async def get_dds_xml(run_id: str, session: SessionDep) -> Response:
    store = RunStore(session)
    dds = await store.get_dds(run_id)
    if dds is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"run {run_id!r} has no DDS")
    if not dds.released:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run {run_id!r} is awaiting review; the DDS is withheld",
        )
    return Response(
        content=dds.xml,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.dds.xml"'},
    )


__all__ = ["router"]
