# Native ECS deployment inputs

Supported role definitions: `controller.compose.yaml`, `worker.compose.yaml`, `nginx.conf`, `init-execution.sql` and the reference-only env templates. Generate private role definitions with `scripts/ecs_native.py`; follow `docs/ecs-native-deployment.md` for initialization and recovery.

`Jenkinsfile.shanghai-*`, `publication.Dockerfile` and the 58 legacy `scripts/ecs_native_*` files listed in the historical manifest are historical acceptance inputs. Their fixed hosts, namespaces, source hashes, images and workspaces describe one past trial. Do not run them against a new release or substitute fresh hashes into old evidence. They are preserved byte-for-byte in a separate Git commit. `docs/ecs-native-acceptance-inputs-2026-10-10.json` records all 67 original inputs and SHA256 values. Runtime stdout, private credentials, source/image archives and receipts remain outside Git.

The accepted source snapshot is commit `1558a120`; historical image/source freeze IDs are documented separately and are not Git commit IDs. Remote Git publication remains paused. Shanghai ECS is powered off as of 2026-10-12.

The reusable same-schema backend rollout entry is `Jenkinsfile.native-release` with `scripts/ecs_native_release.py` and `scripts/ecs_native_release_host.py`. Its private environment template is `release-environment.example.json`. Follow [release CI](../../../docs/ecs-native-release-ci.md); this new path is prepared but not yet cloud-verified.
