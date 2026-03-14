"""Singleton decorator for creating singleton instances."""

from functools import wraps
from typing import Callable, TypeVar

T = TypeVar("T")


def singleton(cls: type[T]) -> Callable[..., T]:
    """Decorator to create a singleton class.

    Usage:
        @singleton
        class MyClass:
            pass

        instance1 = MyClass()
        instance2 = MyClass()
        assert instance1 is instance2  # True

    Args:
        cls: The class to decorate.

    Returns:
        A wrapped class that returns the same instance on every call.
    """
    instances: dict[type[T], T] = {}

    @wraps(cls)
    def get_instance(*args, **kwargs) -> T:
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


def singleton_factory(
    factory_func: Callable[..., T],
) -> Callable[..., T]:
    """Decorator to create a singleton from a factory function.

    Usage:
        @singleton_factory
        def get_my_instance():
            return MyClass()

        instance1 = get_my_instance()
        instance2 = get_my_instance()
        assert instance1 is instance2  # True

    Args:
        factory_func: The factory function to decorate.

    Returns:
        A wrapped function that returns the same instance on every call.
    """
    instance: T | None = None

    @wraps(factory_func)
    def get_instance(*args, **kwargs) -> T:
        nonlocal instance
        if instance is None:
            instance = factory_func(*args, **kwargs)
        return instance

    return get_instance
