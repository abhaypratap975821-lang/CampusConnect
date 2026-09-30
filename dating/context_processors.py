from .models import Notification, StudentProfile


def app_context(request):
    if not request.user.is_authenticated:
        return {"unread_notifications": 0, "current_profile": None}
    profile, _ = StudentProfile.objects.get_or_create(user=request.user)
    return {
        "unread_notifications": Notification.objects.filter(recipient=request.user, read=False).count(),
        "current_profile": profile,
    }
