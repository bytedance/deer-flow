FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-dev curl sudo git \
    build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Pre-install common Python libraries used by skills.
# This eliminates ~30-60s of pip install on every sandbox creation.
RUN pip3 install --no-cache-dir \
    # Data analysis
    duckdb \
    openpyxl \
    pandas \
    numpy \
    # Visualization
    matplotlib \
    seaborn \
    plotly \
    # Document generation
    python-pptx \
    # Image processing
    Pillow \
    # HTTP client
    requests \
    httpx \
    # Video/media APIs
    fal-client \
    # Data formats
    pyyaml \
    xlsxwriter \
    # General utilities
    beautifulsoup4 \
    lxml \
    tabulate \
    scipy

# Create the 'user' account that E2B sandboxes run as
RUN useradd -m -s /bin/bash user \
    && echo "user ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Pre-create the directory structure that the sandbox expects
RUN mkdir -p /mnt/user-data/workspace \
             /mnt/user-data/uploads \
             /mnt/user-data/outputs \
             /mnt/skills \
    && chown -R user:user /mnt/user-data /mnt/skills

# Copy all public skills into the template
COPY skills/ /mnt/skills/public/
RUN chown -R user:user /mnt/skills

USER user
WORKDIR /home/user
