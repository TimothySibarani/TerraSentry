"""Real forest regions used to place synthetic polygons.

Bounding boxes are deliberately inside well-known forest/peat landscapes so that
Hansen GFC and NASA FIRMS return meaningful real data. ``demo_bbox`` narrows a
region to a national park or biosphere area for the hand-picked demo records.
"""

from __future__ import annotations

from dataclasses import dataclass

BBox = tuple[float, float, float, float]


@dataclass(frozen=True)
class Region:
    name: str
    province: str
    kabupaten: str
    bbox: BBox
    demo_bbox: BBox | None = None


REGIONS: tuple[Region, ...] = (
    Region(
        name="Riau peat forests",
        province="Riau",
        kabupaten="Siak",
        bbox=(101.0, -0.9, 102.8, 1.2),
        demo_bbox=(101.9, 0.5, 102.5, 1.1),
    ),
    Region(
        name="Jambi lowland forest",
        province="Jambi",
        kabupaten="Tebo",
        bbox=(101.5, -2.4, 103.2, -0.9),
        demo_bbox=(102.0, -1.4, 102.9, -0.7),
    ),
    Region(
        name="South Sumatra peat forest",
        province="South Sumatra",
        kabupaten="Musi Banyuasin",
        bbox=(102.5, -4.0, 104.5, -2.2),
        demo_bbox=(103.4, -3.2, 104.3, -2.3),
    ),
    Region(
        name="Central Kalimantan forest",
        province="Central Kalimantan",
        kabupaten="Katingan",
        bbox=(111.5, -2.6, 114.0, -0.6),
        demo_bbox=(112.9, -2.5, 113.9, -1.6),
    ),
    Region(
        name="East Kalimantan forest",
        province="East Kalimantan",
        kabupaten="Kutai Timur",
        bbox=(115.5, -0.8, 117.5, 1.2),
        demo_bbox=(116.6, 0.0, 117.4, 0.9),
    ),
    Region(
        name="West Kalimantan forest",
        province="West Kalimantan",
        kabupaten="Kapuas Hulu",
        bbox=(109.5, -1.2, 112.6, 0.9),
        demo_bbox=(111.8, 0.2, 112.5, 0.9),
    ),
)
