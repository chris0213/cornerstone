from fastapi import APIRouter

from .auth import router as auth_router
from .ldap import router as ldap_router
from .sites import router as sites_router
from .racks import router as racks_router
from .circuits import router as circuits_router
from .circuit_incidents import router as circuit_incidents_router
from .ipam import router as ipam_router
from .devices import router as devices_router
from .backups import router as backups_router
from .backup_tasks import router as backup_tasks_router
from .users import router as users_router
from .audit_logs import router as audit_logs_router
from .settings import router as settings_router
from .vlans import router as vlans_router
from .topology import router as topology_router
from .monitoring import router as monitoring_router
from .alerts import router as alerts_router
from .permissions import router as permissions_router
from .dashboard import router as dashboard_router
from .system import router as system_router
from .import_export import router as import_export_router
from .inspection import router as inspection_router
from .ai import router as ai_router
from .timeline import router as timeline_router
from .quick_add import router as quick_add_router
from .reports import router as reports_router
from .changes import router as changes_router
from .knowledge import router as knowledge_router

api_router = APIRouter()

api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(ldap_router, prefix="/auth", tags=["ldap"])
api_router.include_router(sites_router, prefix="/sites", tags=["sites"])
api_router.include_router(racks_router, prefix="/racks", tags=["racks"])
api_router.include_router(circuits_router, prefix="/circuits", tags=["circuits"])
api_router.include_router(circuit_incidents_router, prefix="/circuit-incidents", tags=["circuit-incidents"])
api_router.include_router(ipam_router, prefix="/ipam", tags=["ipam"])
api_router.include_router(vlans_router, prefix="/ipam", tags=["ipam"])
api_router.include_router(devices_router, prefix="/devices", tags=["devices"])
api_router.include_router(backups_router, prefix="/backups", tags=["backups"])
api_router.include_router(backup_tasks_router, prefix="/backup-tasks", tags=["backup-tasks"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(audit_logs_router, prefix="/logs", tags=["logs"])
api_router.include_router(settings_router, prefix="/settings", tags=["settings"])
api_router.include_router(topology_router, prefix="/topology", tags=["topology"])
api_router.include_router(monitoring_router, prefix="/monitor", tags=["monitoring"])
api_router.include_router(alerts_router, prefix="/alerts", tags=["alerts"])
api_router.include_router(permissions_router, prefix="/permissions", tags=["permissions"])
api_router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(system_router, prefix="/system", tags=["system"])
api_router.include_router(import_export_router, prefix="/import-export", tags=["import-export"])
api_router.include_router(inspection_router, tags=["inspection"])
api_router.include_router(ai_router, prefix="/ai", tags=["ai"])
api_router.include_router(timeline_router, prefix="/timeline", tags=["timeline"])
api_router.include_router(quick_add_router, prefix="/devices", tags=["quick-add"])
api_router.include_router(reports_router, prefix="/reports", tags=["reports"])
api_router.include_router(changes_router, prefix="/changes", tags=["changes"])
api_router.include_router(knowledge_router, prefix="/knowledge", tags=["knowledge"])
