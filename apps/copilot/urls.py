from django.urls import path
from .views import CopilotAskView

urlpatterns = [
    path("copilot/ask", CopilotAskView.as_view(), name="copilot-ask"),
]
