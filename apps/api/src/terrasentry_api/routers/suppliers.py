"""Supplier and parcel read endpoints over the seeded synthetic dataset."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from terrasentry_api.schemas import ParcelOut, SupplierDetail, SupplierOut
from terrasentry_api.services import get_session
from terrasentry_api.store import RunStore

router = APIRouter(prefix="/suppliers", tags=["suppliers"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[SupplierOut])
async def list_suppliers(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SupplierOut]:
    store = RunStore(session)
    return [SupplierOut.from_row(row) for row in await store.list_suppliers(limit=limit, offset=offset)]


@router.get("/{supplier_id}", response_model=SupplierDetail)
async def get_supplier(supplier_id: str, session: SessionDep) -> SupplierDetail:
    store = RunStore(session)
    row = await store.get_supplier(supplier_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no supplier {supplier_id!r}")
    detail = SupplierOut.from_row(row)
    return SupplierDetail(
        **detail.model_dump(),
        parcels=[ParcelOut.from_row(parcel) for parcel in row.parcels],
    )


__all__ = ["router"]
