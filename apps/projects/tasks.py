from celery import shared_task
from django.utils import timezone


@shared_task(bind=True)
def generate_project_report(self, report_id):
    from .models import Report, Task

    try:
        report = Report.objects.get(id=report_id)
        project = report.project
        tasks = Task.objects.filter(project=project)

        total = tasks.count()
        done = tasks.filter(status=Task.Status.DONE).count()
        in_progress = tasks.filter(status=Task.Status.IN_PROGRESS).count()
        todo = tasks.filter(status=Task.Status.TODO).count()
        completion_pct = round((done / total * 100) if total > 0 else 0, 2)

        report.data = {
            "project_id": str(project.id),
            "project_name": project.name,
            "total_tasks": total,
            "done": done,
            "in_progress": in_progress,
            "todo": todo,
            "completion_percentage": completion_pct,
        }
        report.status = Report.Status.READY
        report.completed_at = timezone.now()
        report.save()
    except Exception as exc:
        if report_id:
            try:
                from .models import Report
                Report.objects.filter(id=report_id).update(status=Report.Status.FAILED)
            except Exception:
                pass
        raise exc
