import pytest

from truecap.validators import gstin_pan, validate_cin, validate_gstin


@pytest.mark.parametrize("gstin", ["27AAPFU0939F1ZV", "29AAGCB7383J1Z4", " 29aagcb7383j1z4 "])
def test_valid_gstins(gstin):
    ok, _ = validate_gstin(gstin)
    assert ok


@pytest.mark.parametrize(
    "gstin, reason",
    [
        ("27AAPFU0939F1ZA", "checksum"),
        ("27AAPFU0939F1Z", "format"),
        ("27AAPFU0939F1XV", "format"),  # 14th char must be Z
        ("45AAPFU0939F1ZV", "state code"),
        ("", "format"),
    ],
)
def test_invalid_gstins(gstin, reason):
    ok, why = validate_gstin(gstin)
    assert not ok
    assert reason in why


def test_gstin_pan():
    assert gstin_pan("27AAPFU0939F1ZV") == "AAPFU0939F"


def test_cin():
    assert validate_cin("U01100KA2021PTC149876")
    assert not validate_cin("U01100KA2021PTC14987")
