"""File-backed cache fixtures for credential-free rehearsals.

A live run warms the cache; ``export`` snapshots every entry to
``data/fixtures/*.json``; ``prime`` loads those entries back into any
:class:`CacheBackend`. The API can then run with ``CACHE_OFFLINE=true`` so a
cache miss fails fast instead of calling an external source (see
``docs/milestones.md`` M5 "offline demo mode").

Usage:
    uv run python -m terrasentry_integrations.fixtures export --dir data/fixtures
    uv run python -m terrasentry_integrations.fixtures prime --dir data/fixtures
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from terrasentry_integrations.cache import CacheBackend, CacheEntry, build_cache
from terrasentry_integrations.errors import IntegrationError
from terrasentry_integrations.settings import get_integration_settings

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")


def fixture_path(directory: Path, entry: CacheEntry) -> Path:
    """A deterministic, human-readable path for one cache entry."""
    window = _UNSAFE.sub("_", entry.date_window)
    return directory / f"{entry.source}__{entry.geometry_hash[:16]}__{window}.json"


def write_fixture(directory: Path, entry: CacheEntry) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = fixture_path(directory, entry)
    path.write_text(entry.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_fixture(path: Path) -> CacheEntry:
    try:
        return CacheEntry.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except Exception as exc:
        raise IntegrationError(f"invalid fixture {path}: {exc}") from exc


def load_fixtures(directory: Path) -> list[CacheEntry]:
    if not directory.is_dir():
        raise IntegrationError(f"fixture directory {directory} does not exist")
    return [read_fixture(path) for path in sorted(directory.glob("*.json"))]


async def export_fixtures(cache: CacheBackend, directory: Path) -> int:
    """Write every cache entry to ``directory``; returns the number written."""
    entries = await cache.iter_entries()
    for entry in entries:
        write_fixture(directory, entry)
    return len(entries)


async def prime_fixtures(cache: CacheBackend, directory: Path) -> int:
    """Load every fixture in ``directory`` into ``cache``; returns the count."""
    entries = load_fixtures(directory)
    for entry in entries:
        await cache.set(entry)
    return len(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export", "prime"])
    parser.add_argument("--dir", default="data/fixtures", help="fixture directory")
    parser.add_argument(
        "--backend",
        choices=["redis", "memory"],
        default=None,
        help="override CACHE_BACKEND (memory only useful for smoke checks)",
    )
    args = parser.parse_args(argv)

    settings = get_integration_settings()
    backend = args.backend or settings.cache_backend

    async def run() -> int:
        cache = build_cache(settings.model_copy(update={"cache_backend": backend}))
        try:
            if args.command == "export":
                count = await export_fixtures(cache, Path(args.dir))
                print(f"exported {count} cache entries to {args.dir}")
            else:
                count = await prime_fixtures(cache, Path(args.dir))
                print(f"primed {count} cache entries from {args.dir}")
        finally:
            await cache.close()
        return 0

    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "export_fixtures",
    "fixture_path",
    "load_fixtures",
    "main",
    "prime_fixtures",
    "read_fixture",
    "write_fixture",
]
