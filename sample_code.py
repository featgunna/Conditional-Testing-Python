def calculate_discount(age, loyalty_status, first_order):
    if age > 65 and first_order:
        return 0.5
    elif not first_order and (loyalty_status == "gold" or age > 55):
        return 0.3
    elif loyalty_status == "client_kid":
        return 0.2
    else:
        return 0.0