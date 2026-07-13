from rest_framework.permissions import BasePermission
from .models import User


class IsOwnerOrAdmin(BasePermission):
    """Allows access only to users with OWNER or ADMIN role."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in (User.Role.OWNER, User.Role.ADMIN)
        )


class IsOwner(BasePermission):
    """Allows access only to users with OWNER role."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == User.Role.OWNER
        )
