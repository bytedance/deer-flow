def function_tool(*args, **kwargs):
    def decorator(fn):
        return fn

    return decorator
