import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=3,
)
def generate_project_report(self, report_id):
    from .models import Report, Task

    report = Report.objects.get(id=report_id)

    if report.status == Report.Status.READY:
        logger.info("Report %s already READY — skipping.", report_id)
        return

    try:
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
        Report.objects.filter(id=report_id).update(status=Report.Status.FAILED)
        raise exc


@shared_task
def purge_old_reports():
    from .models import Report
    from datetime import timedelta

    cutoff = timezone.now() - timedelta(days=30)
    deleted_count, _ = Report.objects.filter(created_at__lt=cutoff).delete()
    logger.info("purge_old_reports: deleted %d reports older than 30 days.", deleted_count)
    return deleted_count
