from sample_code import calculate_discount

def test_calculate_discount():
    assert calculate_discount(66, "basic", True) == 0.5
    assert calculate_discount(57, "basic", False) == 0.3
    assert calculate_discount(59, "gold", False) == 0.3
    assert calculate_discount(15, "client_kid", True) == 0.2
    assert calculate_discount(22, "gold", False) == 0.3
    assert calculate_discount(62, "basic", True) == 0.0