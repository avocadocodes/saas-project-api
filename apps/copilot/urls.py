from django.urls import path
from .views import CopilotAskView, DocumentsView, DocumentDetailView

urlpatterns = [
    path("copilot/ask", CopilotAskView.as_view(), name="copilot-ask"),
    path("documents", DocumentsView.as_view(), name="documents"),
    path("documents/<uuid:document_id>", DocumentDetailView.as_view(), name="document-detail"),
]
