"""F-14: Audit trail service — logs all admin actions."""
from app.models.audit_log import AuditLog

class AuditService:
    def __init__(self, db):
        self.db = db

    def log(self, action: str, resource_type: str, resource_id: str = None,
            actor_id: str = None, actor_name: str = None, details: dict = None, ip: str = None):
        entry = AuditLog(
            actor_id=actor_id,
            actor_name=actor_name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip,
        )
        self.db.add(entry)
        self.db.commit()
        return entry

    def get_recent(self, limit: int = 50):
        from sqlalchemy import select
        result = self.db.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    def get_by_resource(self, resource_type: str, resource_id: str, limit: int = 20):
        from sqlalchemy import select
        result = self.db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
