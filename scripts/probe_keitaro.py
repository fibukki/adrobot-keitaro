"""One-off probe of the Keitaro Admin API.

Makes exactly one GET per reference endpoint and stores raw responses in
scripts/samples/*.json (git-ignored). The pydantic schemas in app/keitaro/schemas.py
are built from these samples.

The stand logs every request, so the script refuses to run again when samples
already exist; pass --force to re-probe deliberately.

    python -m scripts.probe_keitaro
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

from app.config import get_settings

SAMPLES_DIR = Path(__file__).parent / "samples"

PROBES: list[tuple[str, str, dict[str, str | int]]] = [
    ("campaigns", "/campaigns", {"limit": 5}),
    ("offers", "/offers", {}),
    ("domains", "/domains", {}),
    ("groups_campaigns", "/groups", {"type": "campaigns"}),
    ("traffic_sources", "/traffic_sources", {}),
]


def _describe(payload: object) -> str:
    if isinstance(payload, list):
        keys = sorted(payload[0]) if payload and isinstance(payload[0], dict) else []
        return f"list[{len(payload)}] keys={keys}"
    if isinstance(payload, dict):
        return f"object keys={sorted(payload)}"
    return type(payload).__name__


async def main(force: bool) -> int:
    if SAMPLES_DIR.exists() and any(SAMPLES_DIR.glob("*.json")) and not force:
        print(f"Samples already exist in {SAMPLES_DIR}; use --force to probe again.")
        return 1

    settings = get_settings()
    SAMPLES_DIR.mkdir(exist_ok=True)
    headers = {"Api-Key": settings.keitaro_api_key.get_secret_value()}
    async with httpx.AsyncClient(
        base_url=settings.keitaro_url, headers=headers, timeout=settings.keitaro_timeout
    ) as client:
        for name, path, params in PROBES:
            response = await client.get(path, params=params)
            try:
                payload = response.json()
            except ValueError:
                payload = {"_raw": response.text}
            (SAMPLES_DIR / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"GET {path} {params or ''} -> {response.status_code}: {_describe(payload)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="probe even if samples exist")
    sys.exit(asyncio.run(main(parser.parse_args().force)))
