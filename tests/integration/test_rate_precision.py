"""Precision of `rate` sent as a JSON string and as a JSON number (developer request after
M03 IG-7; D11, D28, contract DL-12).

An accepted rate is stored, returned and carried in VisitCompleted exactly as sent, to the
cent. A rate with more than two decimal places is rejected with 422 (DL-12), never rounded.
The JSON bodies are written by hand so that a number keeps its literal form (`0.10`, not
`0.1`).
"""

import json
import uuid
from decimal import Decimal

import asyncpg
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("no_foreign_consumers")]  # DL-32

ACCEPTED = ["0.10", "19.99"]
REJECTED = ["1.005"]
KINDS = ["string", "number"]


def _body(rate: str, kind: str, description: str) -> str:
    literal = f'"{rate}"' if kind == "string" else rate
    return (
        '{"start_date_time": "2026-11-11T09:00:00Z", "end_date_time": "2026-11-11T11:00:00Z",'
        f' "description": "{description}", "rate": {literal}}}'
    )


async def _post(client, rate: str, kind: str, description: str):
    return await client.post(
        "/api/visits",
        content=_body(rate, kind, description),
        headers={"content-type": "application/json"},
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("rate", ACCEPTED)
async def test_accepted_rate_is_kept_to_the_cent(
    make_client, visits_db: asyncpg.Connection, rate: str, kind: str
) -> None:
    client = make_client()
    response = await _post(client, rate, kind, f"precision {uuid.uuid4()}")
    assert response.status_code == 201, response.text
    visit = response.json()
    assert visit["rate"] == rate

    stored = await visits_db.fetchval(
        "SELECT rate::text FROM visits.visit WHERE id = $1::uuid", visit["id"]
    )
    assert stored == rate
    assert (await client.get(f"/api/visits/{visit['id']}")).json()["rate"] == rate

    completed = await client.post(f"/api/visits/{visit['id']}/complete")
    assert completed.status_code == 202, completed.text
    assert completed.json()["rate"] == rate
    payload = await visits_db.fetchval(
        "SELECT payload FROM visits.outbox WHERE event_id = $1::uuid",
        completed.json()["completion_attempt_id"],
    )
    assert json.loads(payload)["rate"] == rate
    assert Decimal(json.loads(payload)["rate"]) == Decimal(rate)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("rate", REJECTED)
async def test_rate_beyond_the_cent_is_rejected_not_rounded(
    make_client, visits_db: asyncpg.Connection, rate: str, kind: str
) -> None:
    description = f"precision {uuid.uuid4()}"
    response = await _post(make_client(), rate, kind, description)
    assert response.status_code == 422, response.text
    assert await visits_db.fetchval(
        "SELECT count(*) FROM visits.visit WHERE description = $1", description
    ) == 0
