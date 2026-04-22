"""Entry point for running the Gateway API via `python app/main.py`.

Useful for IDE debugging (e.g., PyCharm / VS Code debug configurations).
Equivalent to: PYTHONPATH=. uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001
"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.gateway.app:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
    )
