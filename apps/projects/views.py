from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import Project, Task, Report
from .serializers import ProjectSerializer, TaskSerializer, ReportSerializer
from .permissions import ProjectPermission, ReportPermission
from .filters import TaskFilter, ProjectFilter
from .tasks import generate_project_report


class TenantQuerysetMixin:
    """Ensures all querysets are scoped to the requesting user's organization."""

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class ProjectViewSet(TenantQuerysetMixin, viewsets.ModelViewSet):
    queryset = Project.objects.all().order_by("-created_at")
    serializer_class = ProjectSerializer
    permission_classes = [ProjectPermission]
    filterset_class = ProjectFilter

    @extend_schema(
        responses={202: ReportSerializer},
        summary="Enqueue a project summary report",
    )
    @action(detail=True, methods=["post"], url_path="report")
    def report(self, request, pk=None):
        project = self.get_object()
        report = Report.objects.create(project=project, requested_by=request.user)
        generate_project_report.delay(str(report.id))
        return Response(ReportSerializer(report).data, status=status.HTTP_202_ACCEPTED)


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all().order_by("-created_at")
    serializer_class = TaskSerializer
    permission_classes = [ProjectPermission]
    filterset_class = TaskFilter

    def get_queryset(self):
        return Task.objects.filter(
            project__organization=self.request.user.organization
        ).order_by("-created_at")


class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReportSerializer
    permission_classes = [ReportPermission]

    def get_queryset(self):
        return Report.objects.filter(
            project__organization=self.request.user.organization
        ).order_by("-created_at")
