import importlib


def make_object(module: str, class_name: str, args=None):
    _module = importlib.import_module(module, package=None)
    _class = getattr(_module, class_name)
    return _class() if args is None else _class(**args)


def make_object_from_config(config):
    if isinstance(config, list):
        return [make_object_from_config(i) for i in config]
    elif isinstance(config, dict):
        if 'module' in config and 'class_name' in config:
            if 'args' in config:
                config['args'] = make_object_from_config(config['args'])

            return make_object(**config)
        else:
            return {
                k: make_object_from_config(v)
                for k, v in config.items()
            }
    else:
        return config


def get_session_local(
    session_locals: dict, run_manager, default_session_id: str = "main"
):
    if run_manager is None or "thread_id" not in run_manager.metadata:
        session_id = default_session_id
    else:
        session_id = run_manager.metadata["thread_id"]

    if session_id not in session_locals:
        session_locals[session_id] = dict()

    return session_locals[session_id]
