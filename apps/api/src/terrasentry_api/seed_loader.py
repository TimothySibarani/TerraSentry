"""Load the committed synthetic seed into the audit store.

Idempotent: an already-populated store is left untouched. The API calls this in
the lifespan when ``AUTO_SEED`` is enabled; tests build their own datasets.
"""

from __future__ import annotations

from terrasentry_core.tools.datasets import SeedDatasets

from terrasentry_api.store import RunStore


async def seed_if_empty(store: RunStore, datasets: SeedDatasets) -> int:
    """Populate suppliers/parcels when the store is empty; returns rows seen."""
    if await store.count_suppliers() > 0:
        return 0
    count = await store.seed_suppliers_and_parcels(datasets)
    await store.commit()
    return count


__all__ = ["seed_if_empty"]
