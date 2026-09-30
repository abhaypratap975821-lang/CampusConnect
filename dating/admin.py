from django.contrib import admin

from .models import (
    BlockedUser,
    College,
    Comment,
    ConnectionRequest,
    Conversation,
    ConversationMember,
    Event,
    EventRSVP,
    Interest,
    Like,
    Match,
    Message,
    Notification,
    Post,
    ProfilePhoto,
    Report,
    SavedProfile,
    SkippedProfile,
    StudentProfile,
    StudyGroup,
    StudyGroupMember,
    StudyRequest,
    StudySession,
    UserSettings,
)


@admin.register(
    College,
    StudentProfile,
    ProfilePhoto,
    ConnectionRequest,
    Match,
    SavedProfile,
    SkippedProfile,
    Post,
    Comment,
    Like,
    StudyGroup,
    StudyGroupMember,
    StudyRequest,
    StudySession,
    Event,
    EventRSVP,
    Conversation,
    Message,
    Notification,
    Report,
    BlockedUser,
    UserSettings,
)
class CampusAdmin(admin.ModelAdmin):
    list_display = ("__str__", "created_at")
    search_fields = ("id",)
    list_filter = ("created_at",)


@admin.register(Interest, ConversationMember)
class SimpleAdmin(admin.ModelAdmin):
    list_display = ("__str__",)


admin.site.site_header = "CampusConnect Command Center"
admin.site.site_title = "CampusConnect Admin"
