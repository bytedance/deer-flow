"""Database backup for the Start-Cloud stack."""

import os
import subprocess
from datetime import datetime

from langchain_core.tools import tool

COMPOSE_DIR = os.environ.get("STARTCLOUD_COMPOSE_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "..")))
BACKUP_DIR = os.path.join(COMPOSE_DIR, "backups")
DATABASES = ["keycloak", "vaultwarden", "teable", "twenty"]


@tool
def stack_backup(service: str = "all") -> str:
    """Backup Start-Cloud databases.

    Creates timestamped PostgreSQL dumps for each service database.

    Args:
        service: 'all' to backup everything, or specific database name
                 (keycloak, vaultwarden, nocodb, twenty)
    """
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, timestamp)
    os.makedirs(backup_path, exist_ok=True)

    dbs = DATABASES if service == "all" else [service]
    if service != "all" and service not in DATABASES:
        return f"❌ Unknown database '{service}'. Valid: {', '.join(DATABASES)}"

    results = [f"=== Start-Cloud Backup ({timestamp}) ===\n"]

    for db in dbs:
        dump_file = os.path.join(backup_path, f"{db}.sql")
        cmd = ["docker", "exec", "startcloud-postgres", "pg_dump", "-U", "startcloud", "-d", db, "--clean", "--if-exists"]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                with open(dump_file, "w") as f:
                    f.write(result.stdout)
                size_mb = os.path.getsize(dump_file) / (1024 * 1024)
                results.append(f"✅ {db}: {size_mb:.2f} MB → {dump_file}")
            else:
                results.append(f"❌ {db}: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            results.append(f"❌ {db}: Backup timed out")
        except Exception as e:
            results.append(f"❌ {db}: {e}")

    results.append(f"\nBackup location: {backup_path}")
    return "\n".join(results)
