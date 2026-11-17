"""Vercel serverless function: POST a CSV/XLSX file, get the verified story JSON.

Uses the Vercel Python runtime entrypoint convention: a top-level `app`
(WSGI/ASGI-style) is auto-detected. Kept stdlib-only.

Request:  POST /api/story, raw file bytes in the body (any content type)
Response: story JSON (or a refusal JSON for files too small to support claims)
"""

from __future__ import annotations

import json
import sys
import os

# make the server package importable from the function bundle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.story_engine import profile_bytes, read_csv_bytes, Column, TooBig
from server.xlsx_reader import read_xlsx_bytes, is_xlsx
from server.narrative import build_story


def make_columns(profile, headers):
    cols = []
    for cd in profile["columns"]:
        c = Column(
            name=cd["name"],
            index=headers.index(cd["name"]),
            kind=cd["kind"],
            raw_kind=cd["kind"],
        )
        c.nulls = cd["nulls"]
        c.drop_share = cd["drop_share"]
        c.note = cd.get("note", "")
        c.minv = cd.get("min")
        c.maxv = cd.get("max")
        c.meanv = cd.get("mean")
        c.medv = cd.get("median")
        c.stddev = cd.get("std")
        c.p25 = cd.get("p25")
        c.p75 = cd.get("p75")
        c.top_values = cd.get("top", [])
        cols.append(c)
    return cols


def _read_table(raw):
    """(headers, rows) from either an xlsx or a csv/tsv."""
    if is_xlsx(raw):
        return read_xlsx_bytes(raw)
    return read_csv_bytes(raw)


def handle(request):
    """Vercel Python request handler. `request` carries method + body bytes."""
    try:
        method = (getattr(request, "method", None) or request.get("method") or "").upper()
    except Exception:
        method = "POST"

    if method != "POST":
        return {
            "statusCode": 405,
            "headers": {"Allow": "POST", "Content-Type": "application/json"},
            "body": json.dumps({"ok": False, "error": "POST a CSV or XLSX file to this endpoint."}),
        }

    raw = None
    try:
        raw = request["body"]
    except Exception:
        raw = getattr(request, "body", None)
    if isinstance(raw, str):
        raw = raw.encode("utf-8", "replace")
    if not raw:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"ok": False, "error": "No file received. Send raw CSV/XLSX bytes in the body."}),
        }

    try:
        profile = profile_bytes(raw)
    except TooBig as e:
        return {"statusCode": 413, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"ok": False, "error": str(e)})}
    except Exception as e:
        return {"statusCode": 422, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"ok": False, "error": f"Could not read that file: {e}"})}

    headers, rows = _read_table(raw)

    if profile["too_small"]:
        # honesty response: not enough rows to support a story
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "ok": True,
                "too_small": True,
                "n_rows": profile["n_rows"],
                "min_rows": 20,
                "message": (
                    f"{profile['n_rows']} rows isn't enough to support claims. "
                    "Bring at least 20 and the story engine will say something worth reading."
                ),
                "profile": profile,
            }),
        }

    columns = make_columns(profile, headers)
    story = build_story(headers, rows, columns, profile)
    story["profile"] = profile
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(story),
    }


# --- entrypoints for every convention ----------------------------------------

# modern Vercel Python runtime: request handler function
handler = handle

# WSGI-style app, in case the runtime probes for it
def app(environ, start_response):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
        raw = environ["wsgi.input"].read(length) if length else b""
    except Exception:
        raw = b""
    result = handle({"method": environ.get("REQUEST_METHOD", "POST"), "body": raw})
    body = result["body"].encode()
    status = f"{result['statusCode']} OK" if result["statusCode"] == 200 else f"{result['statusCode']} Error"
    headers = list((result.get("headers") or {}).items()) + [
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    start_response(status, headers)
    return [body]


application = app
main = handle
