from django.db import transaction
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, Invitation
from .serializers import (
    MemberSerializer,
    InvitationSerializer,
    InvitationCreateSerializer,
    AcceptInvitationSerializer,
    UserSerializer,
    _split_name,
)

MANAGER_ROLES = (User.Role.OWNER, User.Role.ADMIN)


def _is_manager(user):
    return user.role in MANAGER_ROLES


def _owner_count(org):
    return User.objects.filter(organization=org, role=User.Role.OWNER).count()


class MembersView(APIView):
    """List everyone in the requesting user's organization."""

    def get(self, request):
        members = User.objects.filter(organization=request.user.organization).order_by(
            "-role", "email"
        )
        data = MemberSerializer(members, many=True).data
        for row in data:
            row["is_self"] = str(row["id"]) == str(request.user.id)
        return Response(data)


class MemberDetailView(APIView):
    """Change a member's role or remove them (managers only)."""

    def _get_target(self, request, member_id):
        return User.objects.filter(
            id=member_id, organization=request.user.organization
        ).first()

    def patch(self, request, member_id):
        if not _is_manager(request.user):
            return Response({"detail": "You don't have permission to manage members."}, status=403)
        target = self._get_target(request, member_id)
        if not target:
            return Response({"detail": "Member not found."}, status=404)

        new_role = request.data.get("role")
        if new_role not in User.Role.values:
            return Response({"detail": "Invalid role."}, status=400)

        # Only an owner may grant or revoke the OWNER role.
        if (new_role == User.Role.OWNER or target.role == User.Role.OWNER) and request.user.role != User.Role.OWNER:
            return Response({"detail": "Only an owner can change owner roles."}, status=403)

        # Never leave the organization without an owner.
        if target.role == User.Role.OWNER and new_role != User.Role.OWNER and _owner_count(request.user.organization) <= 1:
            return Response({"detail": "The organization must have at least one owner."}, status=400)

        target.role = new_role
        target.save(update_fields=["role"])
        return Response(MemberSerializer(target).data)

    def delete(self, request, member_id):
        if not _is_manager(request.user):
            return Response({"detail": "You don't have permission to manage members."}, status=403)
        target = self._get_target(request, member_id)
        if not target:
            return Response({"detail": "Member not found."}, status=404)
        if target.id == request.user.id:
            return Response({"detail": "You can't remove yourself."}, status=400)
        if target.role == User.Role.OWNER and request.user.role != User.Role.OWNER:
            return Response({"detail": "Only an owner can remove an owner."}, status=403)
        if target.role == User.Role.OWNER and _owner_count(request.user.organization) <= 1:
            return Response({"detail": "The organization must have at least one owner."}, status=400)
        target.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationsView(APIView):
    """List pending invitations, or create a new one (managers only)."""

    def get(self, request):
        if not _is_manager(request.user):
            return Response({"detail": "You don't have permission to view invitations."}, status=403)
        invites = Invitation.objects.filter(
            organization=request.user.organization, accepted=False
        )
        return Response(InvitationSerializer(invites, many=True).data)

    def post(self, request):
        if not _is_manager(request.user):
            return Response({"detail": "You don't have permission to invite members."}, status=403)
        serializer = InvitationCreateSerializer(
            data=request.data, context={"organization": request.user.organization}
        )
        serializer.is_valid(raise_exception=True)
        invite = Invitation.objects.create(
            organization=request.user.organization,
            email=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
            invited_by=request.user,
        )
        return Response(InvitationSerializer(invite).data, status=status.HTTP_201_CREATED)


class InvitationDetailView(APIView):
    """Revoke a pending invitation (managers only)."""

    def delete(self, request, invite_id):
        if not _is_manager(request.user):
            return Response({"detail": "You don't have permission."}, status=403)
        invite = Invitation.objects.filter(
            id=invite_id, organization=request.user.organization, accepted=False
        ).first()
        if not invite:
            return Response({"detail": "Invitation not found."}, status=404)
        invite.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvitationInfoView(APIView):
    """Public: look up an invitation by token so the accept page can render it."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        invite = Invitation.objects.filter(token=token).select_related("organization").first()
        if not invite or invite.accepted:
            return Response({"detail": "This invitation is invalid or has already been used."}, status=404)
        return Response({
            "email": invite.email,
            "role": invite.role,
            "organization_name": invite.organization.name,
        })


class AcceptInvitationView(APIView):
    """Public: accept an invitation, create the member, and log them in."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request, token):
        invite = Invitation.objects.filter(token=token).select_related("organization").first()
        if not invite or invite.accepted:
            return Response({"detail": "This invitation is invalid or has already been used."}, status=404)

        serializer = AcceptInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if User.objects.filter(email__iexact=invite.email).exists():
            return Response({"detail": "An account with this email already exists."}, status=400)

        first_name, last_name = _split_name(serializer.validated_data["name"])
        with transaction.atomic():
            user = User.objects.create_user(
                email=invite.email,
                password=serializer.validated_data["password"],
                first_name=first_name,
                last_name=last_name,
                organization=invite.organization,
                role=invite.role,
            )
            invite.accepted = True
            invite.save(update_fields=["accepted"])

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "user": UserSerializer(user).data,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )
