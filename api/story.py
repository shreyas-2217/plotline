"""Vercel serverless function: POST a CSV file, get the verified story JSON back.

Kept dependency-free (stdlib only) so the Vercel Python runtime runs it cold.
"""

from __future__ import annotations

import json
import sys
import os

# make the server package importable from the function bundle
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.story_engine import profile_bytes, read_csv_bytes, Column, TooBig
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


def handler(request):
    method = getattr(request, "method", None) or request.get("method")
    if str(method).upper() != "POST":
        return {
            "statusCode": 405,
            "headers": {"Allow": "POST"},
            "body": json.dumps({"ok": False, "error": "POST a CSV file to this endpoint."}),
        }

    try:
        raw = request["body"]  # bytes
    except Exception:
        raw = None
    if not raw:
        return {
            "statusCode": 400,
            "body": json.dumps({"ok": False, "error": "No file received. Send multipart 'file' or raw CSV bytes."}),
        }

    try:
        profile = profile_bytes(raw)
    except TooBig as e:
        return {"statusCode": 413, "body": json.dumps({"ok": False, "error": str(e)})}
    except Exception as e:
        return {"statusCode": 422, "body": json.dumps({"ok": False, "error": f"Could not read that as CSV: {e}"})}

    headers, rows = read_csv_bytes(raw)

    if profile["too_small"]:
        # honesty response: not enough rows to support a story
        return {
            "statusCode": 200,
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
    return {"statusCode": 200, "body": json.dumps(story)}


# --- Vercel Python runtime entry points -------------------------------------

def main(request):
    return handler(request)
