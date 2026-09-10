"""Deterministic synthetic consignment and EU-operator records for the DDS.

Only the HS heading/product structure follows real EUDR formats; every value is
invented and labelled ``SYNTH-``/``synthetic``. Commodity is derived from the
permit type on the legality record: HGU (plantation land title) -> oil palm,
PBPH (forest utilisation permit) -> wood.
"""

from __future__ import annotations

import random

from terrasentry_core.seed.regions import Region
from terrasentry_core.seed.schemas import (
    Commodity,
    ConsignmentRecord,
    LegalityRecord,
    OperatorRecord,
)

_OPERATOR = OperatorRecord(
    operator_id="OP-SYNTH-001",
    legal_name="SYNTH EU Imports B.V.",
    identifier_type="eori",
    identifier_value="NL998877665544332",
    address_line="SYNTH-Port 1",
    postal_code="3011 XX",
    city="Rotterdam",
    country="NL",
    email="ops@synth.terrasentry.example",
    phone="+31 10 000 0000",
    activity_type="IMPORT",
    country_of_activity="NL",
    border_cross_country="NL",
)


def generate_operator() -> OperatorRecord:
    """The single synthetic EU operator used by every generated consignment."""
    return _OPERATOR.model_copy(deep=True)


def _commodity_for(rng: random.Random, legality: LegalityRecord) -> Commodity:
    if legality.hgu_number is not None and legality.pbp_number is None:
        return "oil_palm"
    if legality.pbp_number is not None and legality.hgu_number is None:
        return "wood"
    return rng.choice(["oil_palm", "wood"])


def generate_consignment(
    rng: random.Random,
    *,
    supplier_id: str,
    index: int,
    legality: LegalityRecord,
    region: Region,
) -> ConsignmentRecord:
    """Build one synthetic consignment lot for a supplier, keyed to its permit type."""
    commodity = _commodity_for(rng, legality)
    area_ha = legality.concession_area_ha
    harvest_year = rng.randint(2023, 2025)
    production_place = f"Block {index:02d} — {region.name} (SYNTH)"
    if commodity == "oil_palm":
        tonnes_per_ha = rng.uniform(3.0, 6.0)
        return ConsignmentRecord(
            supplier_id=supplier_id,
            commodity=commodity,
            description="Crude palm oil (synthetic consignment)",
            hs_heading="1511",
            species_scientific="Elaeis guineensis",
            species_common="Kelapa sawit",
            net_weight_kg=round(tonnes_per_ha * area_ha * 1000.0, 1),
            production_place=production_place,
            harvest_year=harvest_year,
        )
    tonnes_per_ha = rng.uniform(8.0, 14.0)
    net_weight_kg = round(tonnes_per_ha * area_ha * 1000.0, 1)
    return ConsignmentRecord(
        supplier_id=supplier_id,
        commodity=commodity,
        description="Bleached hardwood kraft pulp (synthetic consignment)",
        hs_heading="4703",
        species_scientific="Acacia mangium",
        species_common="Acacia",
        net_weight_kg=net_weight_kg,
        supplementary_unit=round(net_weight_kg / 900.0, 3),
        supplementary_unit_qualifier="MTQ",
        production_place=production_place,
        harvest_year=harvest_year,
    )
