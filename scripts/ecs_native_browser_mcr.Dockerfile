FROM native-core
RUN sed -i 's|http://deb.debian.org|https://mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources \
    && printf 'Acquire::http::Timeout "60";\nAcquire::https::Timeout "60";\nAcquire::Retries "0";\n' > /etc/apt/apt.conf.d/99native-browser-timeout
# Only exact headless-shell1228/FFmpeg1011 artifacts from the verified official OCI layer.
COPY browser-artifacts/ /opt/deerflow-browsers/
# Original CLI owns Debian dependencies, registry links and final install validation.
RUN PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=60000 /app/backend/.venv/bin/python -m playwright install --with-deps --only-shell chromium \
    && chmod -R a+rX /opt/deerflow-browsers \
    && rm -rf /var/lib/apt/lists/*
