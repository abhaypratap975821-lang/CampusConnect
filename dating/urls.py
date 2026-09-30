from django.urls import path

from . import views


urlpatterns = [

    # =========================================================
    # PROFILE PHOTO
    # =========================================================

    path(
        "profile/photo/set/",
        views.set_profile_photo,
        name="set_profile_photo",
    ),

    path(
        "profile/photo/<object_id:photo_id>/delete/",
        views.delete_profile_photo,
        name="delete_profile_photo",
    ),


    # =========================================================
    # HOME / AUTHENTICATION
    # =========================================================

    path(
        "",
        views.home,
        name="home",
    ),

    path(
        "api/health/",
        views.health,
        name="health",
    ),

    path(
        "login/",
        views.login_view,
        name="login",
    ),

    path(
        "register/",
        views.register,
        name="register",
    ),

    path(
        "logout/",
        views.logout_view,
        name="logout",
    ),


    # =========================================================
    # DASHBOARD
    # =========================================================

    path(
        "dashboard/",
        views.dashboard,
        name="dashboard",
    ),


    # =========================================================
    # PROFILE
    # =========================================================

    path(
        "profile/",
        views.profile,
        name="profile",
    ),

    path(
        "profile/user/<object_id:user_id>/",
        views.user_profile,
        name="user_profile",
    ),

    path(
        "profile/user/<object_id:user_id>/match/",
        views.send_profile_match,
        name="send_profile_match",
    ),

    path(
        "profile/edit/",
        views.edit_profile,
        name="edit_profile",
    ),

    path(
        "profile/photo/",
        views.add_photo,
        name="add_photo",
    ),


    # =========================================================
    # DISCOVER
    # =========================================================

    path(
        "discover/",
        views.discover,
        name="discover",
    ),

    path(
        "discover/action/",
        views.discovery_action,
        name="discovery_action",
    ),


    # =========================================================
    # CONNECTIONS
    # =========================================================

    path(
        "connections/",
        views.connections,
        name="connections",
    ),

    path(
        "connections/action/",
        views.connection_action,
        name="connection_action",
    ),


    # =========================================================
    # MATCHES
    # =========================================================

    path(
        "matches/",
        views.matches,
        name="matches",
    ),

    path(
        "matches/<object_id:match_id>/unmatch/",
        views.unmatch,
        name="unmatch",
    ),


    # =========================================================
    # PRIVATE MESSAGES
    # =========================================================

    path(
        "messages/",
        views.messages_view,
        name="messages",
    ),

    path(
        "messages/<object_id:conversation_id>/",
        views.chat,
        name="chat",
    ),

    path(
        "messages/<object_id:conversation_id>/send/",
        views.send_message,
        name="send_message",
    ),


    # =========================================================
    # STUDY MATCH
    # =========================================================

    path(
        "studymatch/",
        views.studymatch,
        name="studymatch",
    ),

    path(
        "studymatch/group/<object_id:group_id>/chat/",
        views.study_group_chat,
        name="study_group_chat",
    ),

    path(
        "studymatch/group/<object_id:group_id>/chat/send/",
        views.send_study_group_message,
        name="send_study_group_message",
    ),

    path(
        "studymatch/message/<object_id:message_id>/delete/",
        views.delete_study_group_message,
        name="delete_study_group_message",
    ),

    path(
        "studymatch/group/<object_id:group_id>/",
        views.study_group_detail,
        name="study_group_detail",
    ),

    path(
        "studymatch/group/create/",
        views.create_study_group,
        name="create_study_group",
    ),

    path(
        "studymatch/group/<object_id:group_id>/join/",
        views.join_study_group,
        name="join_study_group",
    ),

    path(
        "studymatch/group/<object_id:group_id>/delete/",
        views.delete_study_group,
        name="delete_study_group",
    ),

    path(
        "studymatch/group/<object_id:group_id>/member/<object_id:user_id>/remove/",
        views.remove_study_group_member,
        name="remove_study_group_member",
    ),

    path(
        "studymatch/group/<object_id:group_id>/call/",
        views.study_group_call,
        name="study_group_call",
    ),


    # =========================================================
    # EVENTS
    # =========================================================

    path(
        "events/",
        views.events,
        name="events",
    ),

    path(
        "events/create/",
        views.create_event,
        name="create_event",
    ),

    path(
        "events/<object_id:event_id>/",
        views.event_detail,
        name="event_detail",
    ),

    path(
        "events/<object_id:event_id>/delete/",
        views.delete_event,
        name="delete_event",
    ),

    path(
        "events/<object_id:event_id>/rsvp/",
        views.rsvp_event,
        name="rsvp_event",
    ),


    # =========================================================
    # FEED / POSTS
    # =========================================================

    path(
        "feed/",
        views.feed,
        name="feed",
    ),

    path(
        "feed/<object_id:post_id>/",
        views.post_detail,
        name="post_detail",
    ),

    path(
        "feed/<object_id:post_id>/delete/",
        views.delete_post,
        name="delete_post",
    ),

    path(
        "feed/comment/<object_id:comment_id>/delete/",
        views.delete_comment,
        name="delete_comment",
    ),

    path(
        "feed/<object_id:post_id>/like/",
        views.like_post,
        name="like_post",
    ),

    path(
        "feed/<object_id:post_id>/comment/",
        views.comment_post,
        name="comment_post",
    ),

    path(
        "posts/",
        views.posts,
        name="posts",
    ),


    # =========================================================
    # NOTIFICATIONS
    # =========================================================

    path(
        "notifications/",
        views.notifications,
        name="notifications",
    ),

    path(
        "notifications/<object_id:notification_id>/open/",
        views.open_notification,
        name="open_notification",
    ),

    path(
        "notifications/read-all/",
        views.mark_notifications_read,
        name="mark_notifications_read",
    ),


    # =========================================================
    # SEARCH
    # =========================================================

    path(
        "search/",
        views.search,
        name="search",
    ),


    # =========================================================
    # SETTINGS
    # =========================================================

    path(
        "settings/",
        views.settings_view,
        name="settings",
    ),


    # =========================================================
    # SAFETY
    # =========================================================

    path(
        "safety/",
        views.safety,
        name="safety",
    ),

    path(
        "safety/report/",
        views.report,
        name="report",
    ),

    path(
        "safety/unblock/<object_id:user_id>/",
        views.unblock_user,
        name="unblock_user",
    ),
]

