import pytest

from open_child_care_referral_platform.providers.status import status_bucket


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Licensed", "active"),
        ("License", "active"),
        ("Registration", "active"),
        ("Provisional License", "warn"),
        ("Pending Revocation", "warn"),
        ("Suspended", "warn"),
        # "NOT LICENSED" must not read as active just for containing "licensed".
        ("NOT LICENSED", "warn"),
        ("Unlicensed", "warn"),
        ("", "neutral"),
        (None, "neutral"),
        ("Something unexpected", "neutral"),
    ],
)
def test_status_bucket(status, expected):
    assert status_bucket(status) == expected
