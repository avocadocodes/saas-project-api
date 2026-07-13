from django.core.cache import cache
from django.db.models import Count, Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import Project, Task, Report, IdempotencyKey
from .serializers import ProjectSerializer, TaskSerializer, ReportSerializer
from .permissions import ProjectPermission, ReportPermission
from .filters import TaskFilter, ProjectFilter
from .tasks import generate_project_report

PROJECTS_CACHE_TIMEOUT = 300  # 5 minutes


def _org_projects_cache_key(org_id):
    return f"projects:org:{org_id}"


def _project_detail_cache_key(org_id, project_id):
    return f"project:org:{org_id}:id:{project_id}"


class ConflictError(APIException):
    status_code = 409
    default_detail = (
        "Conflict: resource was modified by another request. "
        "Fetch the latest version and retry."
    )
    default_code = "conflict"


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

    def get_queryset(self):
        return (
            Project.objects.filter(organization=self.request.user.organization)
            .annotate(
                task_count=Count("tasks"),
                done_task_count=Count("tasks", filter=Q(tasks__status="DONE")),
            )
            .order_by("-created_at")
        )

    def _org_id(self):
        return self.request.user.organization_id

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)
        cache.delete(_org_projects_cache_key(self._org_id()))

    def perform_update(self, serializer):
        serializer.save()
        org_id = self._org_id()
        cache.delete(_org_projects_cache_key(org_id))
        cache.delete(_project_detail_cache_key(org_id, serializer.instance.pk))

    def perform_destroy(self, instance):
        org_id = self._org_id()
        pid = instance.pk
        instance.delete()
        cache.delete(_org_projects_cache_key(org_id))
        cache.delete(_project_detail_cache_key(org_id, pid))

    def list(self, request, *args, **kwargs):
        cache_key = _org_projects_cache_key(self._org_id())
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached)
        response = super().list(request, *args, **kwargs)
        cache.set(cache_key, response.data, PROJECTS_CACHE_TIMEOUT)
        return response

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
    serializer_class = TaskSerializer
    permission_classes = [ProjectPermission]
    filterset_class = TaskFilter

    def get_queryset(self):
        return (
            Task.objects.filter(project__organization=self.request.user.organization)
            .select_related("assignee", "project")
            .order_by("-created_at")
        )

    def perform_create(self, serializer):
        idempotency_key = self.request.headers.get("Idempotency-Key")
        org = self.request.user.organization

        if idempotency_key:
            existing = (
                IdempotencyKey.objects.filter(key=idempotency_key, organization=org)
                .select_related("task")
                .first()
            )
            if existing and existing.task:
                self._idempotent_task = existing.task
                return

        task = serializer.save()

        if idempotency_key:
            IdempotencyKey.objects.get_or_create(
                key=idempotency_key,
                organization=org,
                defaults={"task": task},
            )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        if hasattr(self, "_idempotent_task"):
            task = self._idempotent_task
            del self._idempotent_task
            return Response(
                TaskSerializer(task, context=self.get_serializer_context()).data,
                status=status.HTTP_200_OK,
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_update(self, serializer):
        instance = serializer.instance
        if_match = self.request.headers.get("If-Match")
        if if_match is not None:
            try:
                client_version = int(if_match)
            except (ValueError, TypeError):
                raise ValidationError({"If-Match": "Must be an integer version number."})
            if instance.version != client_version:
                raise ConflictError()
        serializer.save(version=instance.version + 1)


class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ReportSerializer
    permission_classes = [ReportPermission]

    def get_queryset(self):
        return Report.objects.filter(
            project__organization=self.request.user.organization
        ).order_by("-created_at")
