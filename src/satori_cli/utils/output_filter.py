import re

OUTPUT_REGEX = re.compile(
    r"^(?P<path>[\w\.\-]+?)(\.(?P<result>(stdout|stderr|os_error)))?$"
)


def run_test_filter(filter_tests: list[str], tests: list[dict]) -> list[dict]:
    new_res = []
    for test in tests:
        current_path = test["path"].replace(":", ".")
        for filter_test in filter_tests:
            filter_test = filter_test.replace(":", ".")
            m = OUTPUT_REGEX.match(filter_test)
            if m and current_path == m.group("path"):
                if result := m.group("result"):
                    test["output"] = {result: test["output"][result]}
                    test["filtered_result"] = result
                new_res.append(test)
    return new_res
