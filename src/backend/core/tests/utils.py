"""Utils for testing."""

import json


def assert_equals_partial(actual, expected, debug=False):
    """Assert that the expected dictionary is a subset of the actual dictionary."""
    if debug:
        print(json.dumps(actual, indent=4), json.dumps(expected, indent=4))  # noqa: T201
    if isinstance(actual, list):
        assert len(actual) == len(expected)
        for i, item in enumerate(actual):
            assert_equals_partial(item, expected[i], debug)
    elif isinstance(actual, dict):
        for key, value in expected.items():
            if debug:
                print(f"Asserting {key}: {value}")  # noqa: T201
                print(actual[key])  # noqa: T201
            assert key in actual
            if isinstance(value, (dict, list)):
                assert_equals_partial(actual[key], value, debug)
            else:
                assert actual[key] == value, (
                    f"Key {key}: Expected {value} but got {actual[key]}"
                )
    else:
        assert actual == expected, f"Expected {expected} but got {actual}"
