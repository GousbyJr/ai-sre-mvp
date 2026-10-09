from .coupons import lookup_coupon


def apply_discount(order):
    coupon = lookup_coupon(order.get("coupon_code"))
    return order["total"] - order["total"] * coupon["rate"]


def checkout(order):
    total = apply_discount(order)
    return {"charged": round(total, 2)}
