"""Start-Cloud custom tools for deer-flow agent.

Tools for managing self-hosted open-source SaaS stack:
- stack_deploy: Docker Compose lifecycle management
- stack_status: Health monitoring across all services
- user_onboard: User onboarding (stub — Phase 3 Google Admin SDK)
- user_offboard: Remove user accounts
- stack_backup: Database backups
- service_info: Service catalog and comparison

Teable data management tools:
- teable_list_spaces: Space/Base/Table discovery
- teable_get_fields: Table field/column schema
- teable_query_records: Record query/search/filter
- teable_create_records: Record creation
- teable_update_records: Record modification
- teable_delete_records: Record deletion
- teable_manage_table: Table/field structure management
- teable_aggregate: Aggregation and SQL queries
- teable_show_view: Real-time view embed in artifact panel
"""

from .stack_deploy import stack_deploy
from .stack_status import stack_status
from .stack_backup import stack_backup
from .service_info import service_info
from .user_onboard import user_onboard
from .user_offboard import user_offboard

from .teable_list_spaces import teable_list_spaces
from .teable_get_fields import teable_get_fields
from .teable_query_records import teable_query_records
from .teable_create_records import teable_create_records
from .teable_update_records import teable_update_records
from .teable_delete_records import teable_delete_records
from .teable_manage_table import teable_manage_table
from .teable_aggregate import teable_aggregate
from .teable_show_view import teable_show_view

__all__ = [
    "stack_deploy",
    "stack_status",
    "stack_backup",
    "service_info",
    "user_onboard",
    "user_offboard",
    "teable_list_spaces",
    "teable_get_fields",
    "teable_query_records",
    "teable_create_records",
    "teable_update_records",
    "teable_delete_records",
    "teable_manage_table",
    "teable_aggregate",
    "teable_show_view",
]
