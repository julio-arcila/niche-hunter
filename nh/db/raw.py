"""Encoding for raw payloads.

Raw payloads exist so that re-normalizing history is a query rather than a
re-fetch (ADR-0004). That premise was sized for JSON: a few KB per record. It
does not hold for YouTube's Atom feeds, which return no cache validators — no
ETag, no Last-Modified — so every nightly poll stores ~64 KB of XML per channel,
95% of it identical to last night's. Measured: 95.8 MB from three runs, tracking
toward ~21 GB a year and rising with the channel count.

Payloads above `COMPRESS_OVER` are gzipped into `payload_gz` and `payload` is left
NULL; smaller ones stay as readable JSON so the common case remains inspectable
and queryable with JSON operators. `codec` records which happened, so a reader
never has to guess and a future codec can be added without ambiguity.
"""

from __future__ import annotations

import gzip
import json
from typing import Any

#: Payloads at or below this stay as plain JSON. 4 KB keeps every search hit,
#: video and channel record readable; only bulk documents like feed XML compress.
COMPRESS_OVER = 4_096

CODEC_JSON = "json"
CODEC_GZIP = "gzip"


class UnknownCodec(ValueError):
    pass


def encode(payload: dict[str, Any]) -> dict[str, Any]:
    """Column values for a payload: either `payload` or `payload_gz`, never both."""
    text = json.dumps(payload, separators=(",", ":"), default=str)
    if len(text) <= COMPRESS_OVER:
        return {"payload": payload, "payload_gz": None, "codec": CODEC_JSON}
    return {
        "payload": None,
        "payload_gz": gzip.compress(text.encode(), compresslevel=6),
        "codec": CODEC_GZIP,
    }


def decode(record: Any) -> dict[str, Any]:
    """The payload of a RawRecord, whichever way it was stored."""
    codec = getattr(record, "codec", None) or CODEC_JSON
    if codec == CODEC_JSON:
        return record.payload
    if codec == CODEC_GZIP:
        return json.loads(gzip.decompress(record.payload_gz).decode())
    raise UnknownCodec(f"raw_records.codec={codec!r} is not a codec this build understands")
