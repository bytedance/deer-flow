from importlib.metadata import distribution


def test_installed_distribution_exposes_deerflow_extension_entry_point() -> None:
    entry_points = [entry_point for entry_point in distribution("deerflow-extension-example").entry_points if entry_point.group == "deerflow.extensions"]

    assert [(entry_point.name, entry_point.value) for entry_point in entry_points] == [("example", "deerflow_extension_example:install")]

    install = entry_points[0].load()
    assert install.__deerflow_api__ == "0.2.0"
    assert install.__deerflow_name__ == "example"
