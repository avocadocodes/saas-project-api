from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.projects.models import Project, Task
from . import answer as answer_mod
from . import retrieval


class CopilotAskView(APIView):
    """Ask a grounded question about the workspace. Answers are drawn strictly
    from the org's own projects and tasks, cited by source, and abstain when
    the answer isn't present — scoped to the requesting user's organization."""

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"question": {"type": "string"}}}},
        responses={200: OpenApiResponse(description="Grounded answer with citations")},
    )
    def post(self, request):
        question = (request.data.get("question") or "").strip()
        if not question:
            return Response({"detail": "A question is required."}, status=400)

        org = request.user.organization
        projects = list(Project.objects.filter(organization=org).order_by("created_at"))
        tasks = list(
            Task.objects.filter(project__organization=org)
            .select_related("project", "assignee")
            .order_by("created_at")
        )

        docs = retrieval.build_documents(projects, tasks)
        top = retrieval.rank(question, docs)

        result = answer_mod.ask(question, top)
        result["retrieved"] = len(top)
        result["workspace_items"] = len(docs)
        return Response(result)
