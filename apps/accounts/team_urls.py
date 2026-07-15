from django.urls import path
from .team_views import (
    MembersView,
    MemberDetailView,
    InvitationsView,
    InvitationDetailView,
    InvitationInfoView,
    AcceptInvitationView,
)

urlpatterns = [
    path("members", MembersView.as_view(), name="members"),
    path("members/<uuid:member_id>", MemberDetailView.as_view(), name="member-detail"),
    path("invitations", InvitationsView.as_view(), name="invitations"),
    path("invitations/<uuid:invite_id>", InvitationDetailView.as_view(), name="invitation-detail"),
    path("invitations/token/<str:token>", InvitationInfoView.as_view(), name="invitation-info"),
    path("invitations/token/<str:token>/accept", AcceptInvitationView.as_view(), name="invitation-accept"),
]
