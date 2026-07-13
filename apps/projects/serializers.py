from rest_framework import serializers
from .models import Project, Task, Report


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ["id", "name", "description", "status", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            "id", "project", "title", "description", "status",
            "assignee", "due_date", "version", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_project(self, project):
        user = self.context["request"].user
        if project.organization != user.organization:
            raise serializers.ValidationError("Project does not belong to your organization.")
        return project

    def validate_assignee(self, assignee):
        if assignee is None:
            return assignee
        user = self.context["request"].user
        if assignee.organization != user.organization:
            raise serializers.ValidationError("Assignee does not belong to your organization.")
        return assignee


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ["id", "project", "status", "data", "created_at", "completed_at"]
        read_only_fields = fields
