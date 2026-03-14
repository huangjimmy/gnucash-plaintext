from infrastructure.gnucash.utils import decode_value_from_string


def test_decode_value_from_string():
    assert decode_value_from_string("123") == 123
    assert decode_value_from_string("123.45") == 123.45
    assert decode_value_from_string("true") == "true"
    assert decode_value_from_string("false") == "false"
    assert decode_value_from_string("#True") is True
    assert decode_value_from_string("#False") is False
    assert decode_value_from_string("#123") == 123
    assert decode_value_from_string("#123.45") == 123.45
    assert decode_value_from_string("'hello'") == "'hello'"
    assert decode_value_from_string("None") == "None"
    assert decode_value_from_string("#None") is None
