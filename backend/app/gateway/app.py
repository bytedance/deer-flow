from app.gateway.registrar import register_app


def create_app():
    return register_app()


app = register_app()
