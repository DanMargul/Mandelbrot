from __future__ import annotations

import random
from typing import Any, Final

WORKLOAD_SEED: Final[int] = 20260822
FORWARD: Final[float] = 4800.0
DISCOUNT_FACTOR: Final[float] = 0.9812345

STRIKE_SPAN: Final[tuple[float, float]] = (0.55, 1.65)
EXPIRY_SPAN: Final[tuple[float, float]] = (0.008219, 2.5)
VOLATILITY_SPAN: Final[tuple[float, float]] = (0.07, 0.95)


def pricing_workload(record_count: int) -> dict[str, Any]:
    generator = random.Random(WORKLOAD_SEED)
    records = []
    for index in range(record_count):
        records.append(
            {
                "id": f"option_{index:07d}",
                "forward": FORWARD,
                "strike": FORWARD * generator.uniform(*STRIKE_SPAN),
                "years_to_expiry": generator.uniform(*EXPIRY_SPAN),
                "volatility": generator.uniform(*VOLATILITY_SPAN),
                "discount_factor": DISCOUNT_FACTOR,
                "option_type": generator.choice(["call", "put"]),
            }
        )
    return {"schema": "pricing_request/v1", "records": records}


def implied_volatility_workload(record_count: int, priced_records: list[dict[str, Any]]) -> dict[str, Any]:
    request = pricing_workload(record_count)
    records = []
    for source, priced in zip(request["records"], priced_records, strict=True):
        records.append(
            {
                "id": source["id"],
                "forward": source["forward"],
                "strike": source["strike"],
                "years_to_expiry": source["years_to_expiry"],
                "discount_factor": source["discount_factor"],
                "option_price": priced["price"],
                "option_type": source["option_type"],
            }
        )
    return {"schema": "implied_volatility_request/v1", "records": records}
