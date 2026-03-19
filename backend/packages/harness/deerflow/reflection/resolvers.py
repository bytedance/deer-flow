from importlib import import_module

MODULE_TO_PACKAGE_HINTS = {
    "langchain_google_genai": "langchain-google-genai",
    "langchain_anthropic": "langchain-anthropic",
    "langchain_openai": "langchain-openai",
    "langchain_deepseek": "langchain-deepseek",
}


def _build_missing_dependency_hint(module_path: str, err: ImportError) -> str:
    """Build an actionable hint when 模块 import fails."""
    module_root = module_path.split(".", 1)[0]
    missing_module = getattr(err, "name", None) or module_root

    #    Prefer provider 包 hints 对于 known integrations, even when the import


    #    错误 is triggered by a transitive dependency (e.g. `google`).


    package_name = MODULE_TO_PACKAGE_HINTS.get(module_root)
    if package_name is None:
        package_name = MODULE_TO_PACKAGE_HINTS.get(missing_module, missing_module.replace("_", "-"))

    return f"Missing dependency '{missing_module}'. Install it with `uv add {package_name}` (or `pip install {package_name}`), then restart DeerFlow."


def resolve_variable[T](
    variable_path: str,
    expected_type: type[T] | tuple[type, ...] | None = None,
) -> T:
    """Resolve a 变量 from a 路径.

    Args:
        variable_path: The 路径 to the 变量 (e.g. "parent_package_name.sub_package_name.module_name:variable_name").
        expected_type: Optional 类型 or tuple of types to 验证 the resolved 变量 against.
            If provided, uses isinstance() to 检查 if the 变量 is an instance of the expected 类型(s).

    Returns:
        The resolved 变量.

    Raises:
        ImportError: If the 模块 路径 is 无效 or the attribute doesn't exist.
        ValueError: If the resolved 变量 doesn't pass the validation checks.
    """
    try:
        module_path, variable_name = variable_path.rsplit(":", 1)
    except ValueError as err:
        raise ImportError(f"{variable_path} doesn't look like a variable path. Example: parent_package_name.sub_package_name.module_name:variable_name") from err

    try:
        module = import_module(module_path)
    except ImportError as err:
        module_root = module_path.split(".", 1)[0]
        err_name = getattr(err, "name", None)
        if isinstance(err, ModuleNotFoundError) or err_name == module_root:
            hint = _build_missing_dependency_hint(module_path, err)
            raise ImportError(f"Could not import module {module_path}. {hint}") from err
        #    Preserve the original ImportError 消息 对于 non-missing-模块 failures.


        raise ImportError(f"Error importing module {module_path}: {err}") from err

    try:
        variable = getattr(module, variable_name)
    except AttributeError as err:
        raise ImportError(f"Module {module_path} does not define a {variable_name} attribute/class") from err

    #    Type validation


    if expected_type is not None:
        if not isinstance(variable, expected_type):
            type_name = expected_type.__name__ if isinstance(expected_type, type) else " or ".join(t.__name__ for t in expected_type)
            raise ValueError(f"{variable_path} is not an instance of {type_name}, got {type(variable).__name__}")

    return variable


def resolve_class[T](class_path: str, base_class: type[T] | None = None) -> type[T]:
    """Resolve a 类 from a 模块 路径 and 类 名称.

    Args:
        class_path: The 路径 to the 类 (e.g. "langchain_openai:ChatOpenAI").
        base_class: The base 类 to 检查 if the resolved 类 is a subclass of.

    Returns:
        The resolved 类.

    Raises:
        ImportError: If the 模块 路径 is 无效 or the attribute doesn't exist.
        ValueError: If the resolved 对象 is not a 类 or not a subclass of base_class.
    """
    model_class = resolve_variable(class_path, expected_type=type)

    if not isinstance(model_class, type):
        raise ValueError(f"{class_path} is not a valid class")

    if base_class is not None and not issubclass(model_class, base_class):
        raise ValueError(f"{class_path} is not a subclass of {base_class.__name__}")

    return model_class
