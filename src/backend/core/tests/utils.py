import json

def assert_equals_partial(actual, expected, debug=False):
    if debug:
        print(json.dumps(actual, indent=4), json.dumps(expected, indent=4))
    """Assert that the expected dictionary is a subset of the actual dictionary."""
    if isinstance(actual, list):
        assert len(actual) == len(expected)
        for i, item in enumerate(actual):
            assert_equals_partial(item, expected[i], debug)
    else:
        for key, value in expected.items():
            if debug:
                print(f'Asserting {key}: {value}')
                print(actual[key])
            assert key in actual
            if isinstance(value, dict) or isinstance(value, list):
                assert_equals_partial(actual[key], value, debug)
            else:
                assert actual[key] == value
