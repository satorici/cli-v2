from satori_cli.utils.output_filter import run_test_filter


def test_path_match_includes_test():
    tests = [{"path": "foo.bar", "output": {"stdout": "ok", "stderr": ""}}]
    result = run_test_filter(["foo.bar"], tests)
    assert len(result) == 1
    assert result[0]["output"] == {"stdout": "ok", "stderr": ""}


def test_stdout_filter_narrows_output():
    tests = [{"path": "foo.bar", "output": {"stdout": "ok", "stderr": "err"}}]
    result = run_test_filter(["foo.bar.stdout"], tests)
    assert len(result) == 1
    assert result[0]["output"] == {"stdout": "ok"}
    assert result[0]["filtered_result"] == "stdout"


def test_colon_normalized_to_dot():
    tests = [{"path": "foo.bar", "output": {"stdout": "ok"}}]
    result = run_test_filter(["foo:bar"], tests)
    assert len(result) == 1
