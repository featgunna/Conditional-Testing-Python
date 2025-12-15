from sample_code import calculate_discount

def test_calculate_discount():
    assert calculate_discount(66, "basic", False) == 0.3
    assert calculate_discount(22, "basic", False) == 0.0
    assert calculate_discount(62, "gold", True) == 0.0
    assert calculate_discount(38, "gold", True) == 0.0