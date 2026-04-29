FROM python:3.12-slim-bookworm

# Install system dependencies for Chromium
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
RUN pip install --no-cache-dir \
    "browser-use>=0.2.0" \
    "playwright>=1.40.0" \
    "fastmcp>=2.0.0" \
    "langchain-openai>=1.2.0" \
    "uvicorn[standard]>=0.30.0"

# Install Playwright Chromium + system dependencies
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install chromium --with-deps \
    && rm -rf /var/lib/apt/lists/*

COPY server.py .

EXPOSE 8000

CMD ["python", "server.py"]
