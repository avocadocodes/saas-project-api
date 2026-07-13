from rest_framework.permissions import BasePermission, SAFE_METHODS
from apps.accounts.models import User


class ProjectPermission(BasePermission):
    """
    OWNER/ADMIN: full access including delete.
    MEMBER: read + create + update, no delete.
    """

    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        if request.method == "DELETE":
            return request.user.role in (User.Role.OWNER, User.Role.ADMIN)
        return True


class ReportPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_authenticated
