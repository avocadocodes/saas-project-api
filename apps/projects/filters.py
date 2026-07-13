import django_filters
from .models import Task, Project


class TaskFilter(django_filters.FilterSet):
    class Meta:
        model = Task
        fields = {
            "status": ["exact"],
            "assignee": ["exact"],
            "project": ["exact"],
            "due_date": ["gte", "lte"],
        }


class ProjectFilter(django_filters.FilterSet):
    class Meta:
        model = Project
        fields = {
            "status": ["exact"],
        }
