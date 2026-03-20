# Installation

## Contents
- [Quick install](#quick-install)
- [Docker setup](#docker-setup)
- [Singularity setup (HPC)](#singularity-setup-hpc)
- [nf-core tools (optional)](#nf-core-tools-optional)
- [Verify installation](#verify-installation)
- [Common issues](#common-issues)

## Quick install

```bash
# Nextflow
curl -s https://get.nextflow.io | bash
mv nextflow ~/bin/
export PATH="$HOME/bin:$PATH"

# Verify
nextflow -version
java -version  # Requires 11+
```

## Docker setup

### Linux
```bash
sudo apt-get update && sudo apt-get install docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
# Log out and back in
```

### macOS
Download Docker Desktop: https://docker.com/products/docker-desktop

### Verify
```bash
docker run hello-world
```

## Singularity setup (HPC)

```bash
# Ubuntu/Debian
sudo apt-get install singularity-container

# Or via conda
conda install -c conda-forge singularity
```

### Configure cache
```bash
export NXF_SINGULARITY_CACHEDIR="$HOME/.singularity/cache"
mkdir -p $NXF_SINGULARITY_CACHEDIR
echo 'export NXF_SINGULARITY_CACHEDIR="$HOME/.singularity/cache"' >> ~/.bashrc
```

## nf-core tools (optional)

```bash
pip install nf-core
```

Useful commands:
```bash
nf-core list                    # Available pipelines
nf-core launch rnaseq           # Interactive parameter selection
nf-core download rnaseq -r 3.14.0  # Download for offline use
```

## Verify installation

```bash
nextflow run nf-core/demo -profile test,docker --outdir test_demo
ls test_demo/
```

## Common issues

**Java version wrong:**
```bash
export JAVA_HOME=/path/to/java11
```

**Docker permission denied:**
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

**Nextflow not found:**
```bash
echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```
