COUPONS = {"SAVE10": {"rate": 0.10}, "VIP20": {"rate": 0.20}}


def lookup_coupon(code):
    return COUPONS.get(code)
