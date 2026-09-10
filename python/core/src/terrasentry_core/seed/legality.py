"""Deterministic synthetic legality/entity records in realistic Indonesian formats.

Every name, number, and person here is invented. The trading name carries an explicit
``SYNTH-`` marker and each record sets ``synthetic: true`` with a disclosure string so the
UI and DDS can label it unambiguously (PRD cross-cutting rule 4).
"""

from __future__ import annotations

import random
from typing import Literal

from terrasentry_core.seed.regions import Region
from terrasentry_core.seed.schemas import Archetype, LegalityRecord

_PREFIX_WORDS = ("Sawit", "Hutan", "Agro", "Bumi", "Karya", "Sumber", "Mitra", "Anugerah")
_SUFFIX_WORDS = ("Lestari", "Makmur", "Sejahtera", "Mandiri", "Jaya", "Perkasa", "Sentosa")
_GROUP_WORDS = ("Nusantara", "Sriwijaya", "Borneo", "Andalas", "Khatulistiwa")

_FIRST_NAMES = (
    "Adi",
    "Bayu",
    "Citra",
    "Dewi",
    "Eko",
    "Fitri",
    "Gunawan",
    "Hendra",
    "Indah",
    "Joko",
    "Kartika",
    "Lestari",
    "Maya",
    "Nur",
    "Putra",
    "Rahmat",
    "Sari",
    "Taufik",
    "Wulan",
    "Yusuf",
)
_LAST_NAMES = (
    "Pratama",
    "Wijaya",
    "Santoso",
    "Hartono",
    "Nugroho",
    "Halim",
    "Saputra",
    "Utami",
    "Hidayat",
    "Kusuma",
)


def _digits(rng: random.Random, count: int) -> str:
    first = str(rng.randint(1, 9))
    rest = "".join(str(rng.randint(0, 9)) for _ in range(count - 1))
    return first + rest


def _npwp(rng: random.Random) -> str:
    digits = _digits(rng, 15)
    return f"{digits[0:2]}.{digits[2:5]}.{digits[5:8]}.{digits[8]}-{digits[9:12]}.{digits[12:15]}"


def _person(rng: random.Random) -> str:
    return f"{rng.choice(_FIRST_NAMES)} {rng.choice(_LAST_NAMES)}"


def generate_legality(
    rng: random.Random,
    *,
    supplier_id: str,
    index: int,
    archetype: Archetype,
    region: Region,
) -> LegalityRecord:
    """Build one synthetic supplier/permit record shaped by the target archetype."""
    company = f"PT {rng.choice(_PREFIX_WORDS)} {rng.choice(_SUFFIX_WORDS)} {rng.choice(_GROUP_WORDS)}"
    trading = f"{company.removeprefix('PT ')} (SYNTH-{index:03d})"
    year = rng.randint(2005, 2020)
    hgu_number = f"HGU No. {rng.randint(10, 999)}/HGU/BPN/{year}"
    pbp_number = f"SK.{rng.randint(100, 9999)}/MENLHK-PKTL/PBPH/{year}"

    permit_status: Literal["active", "expired", "suspended", "none"]
    certifications: list[str]
    sanctions: list[str]
    hgu: str | None
    pbp: str | None

    if archetype == "compliant":
        permit_status = "active"
        certifications = ["ISPO"]
        sanctions = []
        hgu, pbp = hgu_number, None
    elif archetype == "high_risk":
        permit_status = rng.choice(["suspended", "expired"])
        certifications = []
        sanctions = [f"{rng.randint(2018, 2024)} permit suspension (synthetic)"]
        if rng.random() < 0.5:
            hgu, pbp = hgu_number, None
        else:
            hgu, pbp = None, pbp_number
    else:
        permit_status = "active"
        certifications = rng.sample(["ISPO", "RSPO"], k=1)
        sanctions = []
        hgu, pbp = hgu_number, pbp_number if rng.random() < 0.5 else None

    return LegalityRecord(
        supplier_id=supplier_id,
        legal_name=company,
        trading_name=trading,
        group=f"Grup {rng.choice(_GROUP_WORDS)}",
        nib=_digits(rng, 13),
        npwp=_npwp(rng),
        hgu_number=hgu,
        pbp_number=pbp,
        permit_status=permit_status,
        concession_area_ha=round(rng.uniform(500.0, 18_000.0), 1),
        province=region.province,
        kabupaten=region.kabupaten,
        beneficial_owners=[_person(rng), _person(rng)],
        certifications=certifications,
        sanctions=sanctions,
    )
