#!/usr/bin/env python3
"""Download Amazon's root CA certificates into a PEM bundle.

Only needed where the system trust store does not already carry them --
most Linux distributions do, and `athleteiq.chain.load_anchors()` finds them
there without any of this. Run it when a container image ships a minimal CA
bundle, or when you would rather pin to a file you control than to whatever the
base image happens to include.

    python scripts/fetch_amazon_roots.py --out amazon-roots.pem
    export ATHLETEIQ_SNS_CA_BUNDLE=$PWD/amazon-roots.pem

Deliberately a fetch rather than a checked-in file: an embedded certificate is
one that silently goes stale, and a root written into source control is a root
nobody re-checks.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Amazon publishes these at stable, documented URLs.
ROOT_URLS = (
    "https://www.amazontrust.com/repository/AmazonRootCA1.pem",
    "https://www.amazontrust.com/repository/AmazonRootCA2.pem",
    "https://www.amazontrust.com/repository/AmazonRootCA3.pem",
    "https://www.amazontrust.com/repository/AmazonRootCA4.pem",
    "https://www.amazontrust.com/repository/SFSRootCAG2.pem",
)


def fetch(url: str, timeout: int = 15) -> bytes:
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="amazon-roots.pem")
    parser.add_argument(
        "--from-system", action="store_true",
        help="extract them from the local trust store instead of downloading",
    )
    args = parser.parse_args()

    from athleteiq import chain

    if args.from_system:
        anchors = chain.load_anchors(pin_to_amazon=True)
        from cryptography.hazmat.primitives import serialization

        blob = b"".join(
            a.public_bytes(serialization.Encoding.PEM) for a in anchors
        )
        source = "the system trust store"
    else:
        chunks = []
        for url in ROOT_URLS:
            try:
                chunks.append(fetch(url))
                print(f"  fetched {url.rsplit('/', 1)[-1]}")
            except Exception as exc:  # noqa: BLE001
                print(f"  FAILED {url}: {exc}", file=sys.stderr)
        blob = b"\n".join(chunks)
        source = "amazontrust.com"

    # Parsed before writing, so a truncated download is caught here rather than
    # at the first bounce webhook.
    certificates = chain.load_pem_bundle(blob)
    if not certificates:
        print("no certificates were obtained", file=sys.stderr)
        return 1

    Path(args.out).write_bytes(blob)
    print(f"\nwrote {len(certificates)} certificates from {source} to {args.out}")
    for certificate in certificates:
        print(f"  {certificate.subject.rfc4514_string()}")
    print(f"\n  export ATHLETEIQ_SNS_CA_BUNDLE={Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
