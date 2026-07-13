from django.core.management.base import BaseCommand
from django.db import connection, reset_queries
from django.conf import settings


class Command(BaseCommand):
    help = "Benchmark naive vs optimized query counts for the task list queryset"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tasks",
            type=int,
            default=200,
            help="Number of tasks to seed (default: 200)",
        )

    def handle(self, *args, **options):
        n = options["tasks"]
        self._run(n)

    def _run(self, n):
        from apps.accounts.models import Organization, User
        from apps.projects.models import Project, Task

        self.stdout.write(f"Seeding {n} tasks in a fresh org...")

        org = Organization.objects.create(name="BenchmarkOrg", slug=f"benchmark-{n}-{id(self)}")
        user = User.objects.create_user(
            email=f"bench-{id(self)}@benchmark.example",
            password="x",
            organization=org,
            role=User.Role.OWNER,
        )
        project = Project.objects.create(organization=org, name="Bench Project")
        Task.objects.bulk_create([
            Task(project=project, title=f"Task {i}", status=Task.Status.TODO)
            for i in range(n)
        ])

        settings.DEBUG = True

        self.stdout.write("Running naive queryset (no select_related)...")
        reset_queries()
        naive_qs = list(Task.objects.filter(project__organization=org).order_by("-created_at"))
        # Touch related fields to force N+1
        for task in naive_qs:
            _ = str(task.assignee)
            _ = str(task.project)
        naive_count = len(connection.queries)
        reset_queries()

        self.stdout.write("Running optimized queryset (select_related)...")
        optimized_qs = list(
            Task.objects.filter(project__organization=org)
            .select_related("assignee", "project")
            .order_by("-created_at")
        )
        for task in optimized_qs:
            _ = str(task.assignee)
            _ = str(task.project)
        optimized_count = len(connection.queries)
        reset_queries()

        settings.DEBUG = False

        self.stdout.write(self.style.SUCCESS(
            f"\n{'=' * 50}\n"
            f"benchmark_queries results ({n} tasks)\n"
            f"  naive (no select_related):   {naive_count} queries\n"
            f"  optimized (select_related):  {optimized_count} queries\n"
            f"{'=' * 50}"
        ))
