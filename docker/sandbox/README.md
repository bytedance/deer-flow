# Sandbox Image For `features-tool`

This image extends DeerFlow's default AIO sandbox image, copies
`docker/sandbox/features-tool` into the image, and preinstalls the Python
dependencies it requires.

## Included dependency source

- `docker/sandbox/features-tool/`
- `docker/sandbox/features-tool/requirements.txt`

## Build

From the repository root:

```bash
docker build \
  -f docker/sandbox/Dockerfile \
  -t deer-flow-sandbox-features-tool:latest \
  docker/sandbox
```

If you need a custom Python package mirror:

```bash
docker build \
  --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  -f docker/sandbox/Dockerfile \
  -t deer-flow-sandbox-features-tool:latest \
  docker/sandbox
```

## Use

`config.yaml` is configured to use:

```yaml
sandbox:
  image: deer-flow-sandbox-features-tool:latest
  environment:
    FEATURES_TOOL_ROOT: /opt/features-tool
```

If you run DeerFlow on another machine or registry, retag and push the image,
then replace the image name in `config.yaml`.
