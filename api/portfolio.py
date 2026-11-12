"""Portfolio valuation: combine stored holdings with live prices."""
from decimal import Decimal


def valuate(holdings, prices: dict[str, dict], vs_currency: str) -> dict:
    rows = []
    total_value = Decimal(0)
    total_cost = Decimal(0)

    for h in holdings:
        cost = h.amount * h.avg_buy_price
        live = prices.get(h.coin_id)
        row = {
            "coin_id": h.coin_id,
            "amount": h.amount,
            "avg_buy_price": h.avg_buy_price,
            "price": None,
            "value": None,
            "cost": cost,
            "pnl": None,
            "pnl_pct": None,
        }
        if live and live.get("price") is not None:
            price = Decimal(str(live["price"]))
            value = h.amount * price
            pnl = value - cost
            row.update(
                price=price,
                value=value,
                pnl=pnl,
                pnl_pct=(pnl / cost * 100).quantize(Decimal("0.01")) if cost > 0 else None,
            )
            total_value += value
            total_cost += cost
        rows.append(row)

    total_pnl = total_value - total_cost
    return {
        "vs_currency": vs_currency,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pnl": total_pnl,
        "total_pnl_pct": (total_pnl / total_cost * 100).quantize(Decimal("0.01")) if total_cost > 0 else None,
        "holdings": rows,
    }
