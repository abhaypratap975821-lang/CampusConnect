from datetime import date

from django.contrib import messages as flash
from django.utils import timezone
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import (
    CommentForm,
    EventForm,
    PhotoForm,
    PostForm,
    ProfileForm,
    RegistrationForm,
    ReportForm,
    StudyGroupForm,
)
from .models import (
    BlockedUser,
    College,
    Comment,
    ConnectionRequest,
    Conversation,
    ConversationMember,
    Event,
    EventRSVP,
    Like,
    Match,
    Message,
    Notification,
    Post,
    ProfilePhoto,
    SavedProfile,
    SkippedProfile,
    StudentProfile,
    StudyGroup,
    StudyGroupMember,
    StudyRequest,
    UserSettings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def notify(user, kind, text, link=""):
    Notification.objects.create(recipient=user, kind=kind, text=text, link=link)


def notify_new_message(conversation, sender, recipient):
    """One unread 'message' notification per conversation, refreshed on each
    new message, rather than piling up a notification per message."""
    link = reverse("chat", args=[conversation.id])
    text = f"New message from {sender.get_full_name() or sender.username}"
    existing = Notification.objects.filter(recipient=recipient, kind="message", link=link, read=False).first()
    if existing:
        existing.text = text
        existing.created_at = timezone.now()
        existing.save(update_fields=["text", "created_at"])
    else:
        notify(recipient, "message", text, link)


def get_profile(user):
    profile, _ = StudentProfile.objects.get_or_create(user=user)
    return profile


def is_blocked(user_a, user_b):
    """True if either user has blocked the other. Never trusts frontend state."""
    if user_a.id == user_b.id:
        return False
    return BlockedUser.objects.filter(
        Q(blocker=user_a, blocked=user_b) | Q(blocker=user_b, blocked=user_a)
    ).exists()


def sever_relationship(user_a, user_b):
    """Used when a block happens: cancels pending requests and removes any
    active match/conversation between the two users so the block can't be
    bypassed through an existing connection."""
    ConnectionRequest.objects.filter(
        Q(sender=user_a, receiver=user_b) | Q(sender=user_b, receiver=user_a)
    ).exclude(status="cancelled").update(status="cancelled")
    Match.objects.filter(
        Q(user_a=user_a, user_b=user_b) | Q(user_a=user_b, user_b=user_a)
    ).delete()  # cascades to the private Conversation + its Messages


ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
ALLOWED_ATTACHMENT_EXTENSIONS = {
    "jpg", "jpeg", "png", "webp", "pdf",
    "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt",
    "mp4", "mov", "webm",
}
MAX_IMAGE_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENT_UPLOAD_BYTES = 60 * 1024 * 1024


def validate_upload(file_obj, allowed_extensions, max_bytes=MAX_IMAGE_UPLOAD_BYTES):
    """Server-side validation for uploads that bypass a Django ModelForm
    (and therefore never actually ran the model field validators). Returns
    an error message, or None if the file passes."""
    if not file_obj:
        return "Please choose a file."
    name = getattr(file_obj, "name", "") or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in allowed_extensions:
        return f"That file type isn't allowed. Allowed types: {', '.join(sorted(allowed_extensions))}."
    if file_obj.size > max_bytes:
        return f"That file is too large. Max size is {max_bytes // (1024 * 1024)} MB."
    return None


def _shared_tokens(left_value, right_value):
    """Return whether two comma/space separated profile fields overlap."""
    if not left_value or not right_value:
        return False
    normalize = lambda value: {
        token.strip().casefold()
        for token in str(value).replace("/", ",").replace("|", ",").split(",")
        for token in token.split()
        if token.strip()
    }
    return bool(normalize(left_value) & normalize(right_value))


def _normalise_profile_text(value):
    """Normalize a profile value for reliable same-field matching."""
    value = " ".join(str(value or "").strip().casefold().split())
    return value.replace("&", "and").replace(".", "")


def _profile_values_match(left_value, right_value):
    """Match equal profile values while tolerating harmless formatting differences."""
    left = _normalise_profile_text(left_value)
    right = _normalise_profile_text(right_value)
    if not left or not right:
        return False
    if left == right:
        return True

    # A few common campus abbreviations should still behave like the same course.
    aliases = {
        "ds": "data science",
        "data sci": "data science",
        "cs": "computer science",
        "cse": "computer science engineering",
        "it": "information technology",
        "ict": "information and communication technology",
    }
    return aliases.get(left, left) == aliases.get(right, right)


def matching_attributes(left, right):
    """Return the four primary campus signals used by Discover.

    A student is discoverable when at least one of these is shared with the
    viewer: college, course, year, or city. The number of shared signals is
    used to rank the cards. Additional interests are intentionally not required
    for a card to appear, because the requested Discover behavior is based on
    these four campus/profile fields.
    """
    matches = []

    if left.college_id and right.college_id and left.college_id == right.college_id:
        matches.append("college")
    if left.year and right.year and left.year == right.year:
        matches.append("year")
    if _profile_values_match(left.course, right.course):
        matches.append("course")
    if _profile_values_match(left.city, right.city):
        matches.append("city")

    return matches


def compatibility(left, right):
    """Display compatibility based on actual shared profile attributes."""
    match_count = len(matching_attributes(left, right))
    return min(100, 60 + match_count * 10)


def create_match_conversation(match):
    """Create/get the private 1-to-1 conversation for an active Match."""
    conversation, _ = Conversation.objects.get_or_create(match=match)

    ConversationMember.objects.get_or_create(
        conversation=conversation,
        user_id=match.user_a_id,
    )
    ConversationMember.objects.get_or_create(
        conversation=conversation,
        user_id=match.user_b_id,
    )
    return conversation


def get_or_create_conversation(user_a, user_b):
    """Backward-compatible helper that only works for an active Match."""
    match = Match.objects.filter(
        Q(user_a=user_a, user_b=user_b)
        | Q(user_a=user_b, user_b=user_a)
    ).first()
    if not match:
        return None
    return create_match_conversation(match)


def wants_json(request):
    return (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in request.headers.get("accept", "")
    )


def match_request_response(request, *, success, status, message, extra=None, fallback="matches"):
    payload = {
        "success": success,
        "status": status,
        "message": message,
    }
    if extra:
        payload.update(extra)

    if wants_json(request):
        return JsonResponse(payload, status=200 if success else 400)

    if success:
        flash.success(request, message)
    else:
        flash.error(request, message)
    return redirect(request.POST.get("next") or fallback)


# ---------------------------------------------------------------------------
# Public profile / profile actions
# ---------------------------------------------------------------------------

@login_required
def user_profile(request, user_id):
    viewed_user = get_object_or_404(User, id=user_id)

    if viewed_user.id == request.user.id:
        return redirect("profile")

    if is_blocked(request.user, viewed_user):
        flash.error(request, "This profile isn't available.")
        return redirect("discover")

    connection = (
        ConnectionRequest.objects
        .filter(
            Q(sender=request.user, receiver=viewed_user) |
            Q(sender=viewed_user, receiver=request.user)
        )
        .exclude(status="cancelled")
        .order_by("-created_at")
        .first()
    )

    match = Match.objects.filter(
        Q(user_a=request.user, user_b=viewed_user) |
        Q(user_a=viewed_user, user_b=request.user)
    ).first()

    is_connected = bool(match) or (connection is not None and connection.status == "accepted")

    profile = get_profile(viewed_user)
    viewed_settings, _ = UserSettings.objects.get_or_create(user=viewed_user)
    # Profile visibility controls direct profile pages; active matches retain access.
    # Discoverability is a separate control used by the discovery feed.
    if not viewed_settings.profile_visible and not is_connected:
        flash.error(request, "This profile is private.")
        return redirect("discover")

    posts = (
        Post.objects
        .filter(author=viewed_user, hidden=False)
        .select_related("author", "author__student_profile")
        .prefetch_related("likes", "comments__author")
    )

    liked_ids = set(
        Like.objects.filter(
            user=request.user,
            post__in=posts
        ).values_list("post_id", flat=True)
    )

    followers_count = ConnectionRequest.objects.filter(
        receiver=viewed_user,
        status="accepted",
    ).count()

    following_count = ConnectionRequest.objects.filter(
        sender=viewed_user,
        status="accepted",
    ).count()

    can_view_posts = bool(match)
    visible_posts_count = posts.count() if can_view_posts else 0

    return render(request, "profile.html", {
        "profile": profile,
        "posts": posts,
        "liked_ids": liked_ids,
        "comment_form": CommentForm(),
        "posts_count": visible_posts_count,
        "followers_count": followers_count,
        "following_count": following_count,
        "is_own_profile": False,
        "can_view_posts": can_view_posts,
        "viewed_user": viewed_user,
        "connection": connection,
        "match": match,
    })


@login_required
@require_POST
def send_profile_match(request, user_id):
    """Send a match request; a Match is created only after acceptance."""
    target = get_object_or_404(User, id=user_id)

    if target.id == request.user.id:
        return match_request_response(
            request, success=False, status="error",
            message="You cannot match with yourself.", fallback="discover",
        )

    if is_blocked(request.user, target):
        return match_request_response(
            request, success=False, status="blocked",
            message="You can't send a match request to this person.", fallback="discover",
        )

    already_matched = Match.objects.filter(
        Q(user_a=request.user, user_b=target)
        | Q(user_a=target, user_b=request.user)
    ).first()

    if already_matched:
        conversation = create_match_conversation(already_matched)
        return match_request_response(
            request, success=True, status="matched",
            message="You are already matched with this person.",
            extra={
                "match_id": already_matched.id,
                "conversation_id": conversation.id,
            },
            fallback="discover",
        )

    outgoing = ConnectionRequest.objects.filter(
        sender=request.user, receiver=target
    ).first()
    incoming = ConnectionRequest.objects.filter(
        sender=target, receiver=request.user
    ).first()

    if outgoing and outgoing.status == "pending":
        return match_request_response(
            request, success=True, status="pending",
            message="Match request already sent.",
            extra={"request_id": outgoing.id}, fallback="discover",
        )

    if incoming and incoming.status == "pending":
        return match_request_response(
            request, success=True, status="incoming",
            message="This person has already sent you a match request. Check Matches.",
            extra={"request_id": incoming.id}, fallback="discover",
        )

    # Old accepted rows without an active Match are stale. Make them reusable.
    if outgoing and outgoing.status == "accepted":
        outgoing.status = "rejected"
        outgoing.save(update_fields=["status"])
    if incoming and incoming.status == "accepted":
        incoming.status = "rejected"
        incoming.save(update_fields=["status"])

    if outgoing and outgoing.status in {"rejected", "cancelled"}:
        outgoing.status = "pending"
        outgoing.super_connect = False
        outgoing.save(update_fields=["status", "super_connect"])
        request_obj = outgoing
    else:
        if incoming and incoming.status in {"rejected", "cancelled"}:
            incoming.delete()
        request_obj = ConnectionRequest.objects.create(
            sender=request.user,
            receiver=target,
            status="pending",
            super_connect=False,
        )

    notify(
        target,
        "connection",
        f"{request.user.get_full_name() or request.user.username} sent you a match request.",
        reverse("matches"),
    )

    return match_request_response(
        request, success=True, status="pending",
        message="Match request sent.",
        extra={"request_id": request_obj.id}, fallback="discover",
    )

# ---------------------------------------------------------------------------
# Core / auth
# ---------------------------------------------------------------------------

def home(request):
    return redirect("dashboard") if request.user.is_authenticated else render(request, "home.html")


def health(request):
    return JsonResponse({"ok": True, "service": "CampusConnect", "database": "sqlite"})


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        flash.success(request, "Welcome to CampusConnect — let's make your campus feel smaller.")
        return redirect("edit_profile")
    return render(request, "auth/register.html", {"form": form})


def login_view(request):
    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        flash.success(request, "Welcome back to your campus.")
        return redirect(request.GET.get("next") or "dashboard")
    return render(request, "auth/login.html", {"form": form})


def logout_view(request):
    logout(request)
    flash.info(request, "You've been signed out safely.")
    return redirect("home")


# ---------------------------------------------------------------------------
# Dashboard / profile
# ---------------------------------------------------------------------------

@login_required
@require_POST
def set_profile_photo(request):
    profile = get_profile(request.user)
    form = PhotoForm(request.POST, request.FILES)

    if not form.is_valid():
        flash.error(request, "Please upload a valid JPG, PNG, or WebP image under 8 MB.")
        return redirect("profile")

    image = form.cleaned_data["image"]
    error = validate_upload(image, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_UPLOAD_BYTES)
    if error:
        flash.error(request, error)
        return redirect("profile")

    ProfilePhoto.objects.create(
        profile=profile,
        image=image,
        is_primary=True,
    )

    flash.success(request, "Profile photo updated successfully.")
    return redirect("profile")


@login_required
@require_POST
def delete_profile_photo(request, photo_id):
    photo = get_object_or_404(
        ProfilePhoto,
        id=photo_id,
        profile__user=request.user,
    )

    photo.image.delete(save=False)
    photo.delete()

    remaining = ProfilePhoto.objects.filter(profile=photo.profile).order_by("created_at")

    if remaining.exists() and not remaining.filter(is_primary=True).exists():
        remaining.first().save(update_fields=["is_primary"])

    flash.success(request, "Profile photo removed successfully.")
    return redirect("profile")

@login_required
def dashboard(request):
    profile = get_profile(request.user)
    match_qs = (
        Match.objects
        .filter(Q(user_a=request.user) | Q(user_b=request.user))
        .select_related("user_a", "user_b")
    )
    upcoming = Event.objects.filter(
        date__gte=date.today()
    ).order_by("date", "start_time")[:3]
    pending_count = ConnectionRequest.objects.filter(
        receiver=request.user, status="pending"
    ).count()
    unread = Message.objects.filter(
        conversation__members__user=request.user,
        read_at__isnull=True,
    ).exclude(sender=request.user).count()

    return render(request, "dashboard.html", {
        "profile": profile,
        "active_matches_count": match_qs.count(),
        "pending_match_count": pending_count,
        "unread": unread,
        "upcoming": upcoming,
    })


@login_required
def profile(request):
    profile = get_profile(request.user)

    posts = (
        Post.objects
        .filter(author=request.user, hidden=False)
        .select_related("author", "author__student_profile")
        .prefetch_related("likes", "comments__author")
    )

    liked_ids = set(
        Like.objects.filter(
            user=request.user,
            post__in=posts
        ).values_list("post_id", flat=True)
    )

    followers_count = ConnectionRequest.objects.filter(
        receiver=request.user,
        status="accepted",
    ).count()

    following_count = ConnectionRequest.objects.filter(
        sender=request.user,
        status="accepted",
    ).count()

    return render(request, "profile.html", {
        "profile": profile,
        "posts": posts,
        "liked_ids": liked_ids,
        "comment_form": CommentForm(),
        "posts_count": posts.count(),
        "followers_count": followers_count,
        "following_count": following_count,
        "is_own_profile": True,
    })


@login_required
def edit_profile(request):
    profile = get_profile(request.user)
    form = ProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        edited = form.save(commit=False)
        edited.looking_for = form.cleaned_data.get("looking_for", [])
        edited.save()
        form.save_m2m()
        flash.success(request, "Your profile is looking good.")
        return redirect("profile")
    return render(request, "edit_profile.html", {"form": form, "profile": profile})


@login_required
@require_POST
def add_photo(request):
    form = PhotoForm(request.POST, request.FILES)
    if form.is_valid():
        image = form.cleaned_data["image"]
        error = validate_upload(image, ALLOWED_IMAGE_EXTENSIONS, MAX_IMAGE_UPLOAD_BYTES)
        if error:
            flash.error(request, error)
        else:
            profile = get_profile(request.user)
            ProfilePhoto.objects.create(
                profile=profile,
                image=image,
                is_primary=not profile.photos.exists(),
            )
            flash.success(request, "Photo added to your gallery.")
    else:
        flash.error(request, "Please upload a JPG, PNG, or WebP image under 8 MB.")
    return redirect("profile")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

@login_required
def discover(request):
    profile = get_profile(request.user)
    candidates = (
        StudentProfile.objects
        .filter(discoverable=True, user__is_active=True)
        .exclude(user=request.user)
        .select_related("user", "college")
        .prefetch_related("interests", "photos")
    )

    blocked_ids = BlockedUser.objects.filter(blocker=request.user).values_list("blocked_id", flat=True)
    blocked_by_ids = BlockedUser.objects.filter(blocked=request.user).values_list("blocker_id", flat=True)
    skipped_ids = SkippedProfile.objects.filter(user=request.user).values_list("profile_id", flat=True)

    candidates = (
        candidates
        .exclude(user_id__in=blocked_ids)
        .exclude(user_id__in=blocked_by_ids)
        .exclude(id__in=skipped_ids)
    )

    # Explicit filters are optional refinements. Without them, Discover uses
    # the viewer's own college/course/year/city signals automatically.
    filters = {
        "course": request.GET.get("course", "").strip(),
        "year": request.GET.get("year", "").strip(),
        "college": request.GET.get("college", "").strip(),
        "city": request.GET.get("city", "").strip(),
    }

    if filters["course"]:
        candidates = candidates.filter(course__icontains=filters["course"])
    if filters["year"]:
        candidates = candidates.filter(year=filters["year"])
    if filters["city"]:
        candidates = candidates.filter(city__icontains=filters["city"])
    if filters["college"]:
        candidates = candidates.filter(college_id=filters["college"])

    active_match_user_ids = set()
    match_qs = Match.objects.filter(Q(user_a=request.user) | Q(user_b=request.user))
    for user_a_id, user_b_id in match_qs.values_list("user_a_id", "user_b_id"):
        active_match_user_ids.update((user_a_id, user_b_id))
    active_match_user_ids.discard(request.user.id)

    candidate_user_ids = list(candidates.values_list("user_id", flat=True))
    pending_outgoing = set(
        ConnectionRequest.objects
        .filter(sender=request.user, receiver_id__in=candidate_user_ids, status="pending")
        .values_list("receiver_id", flat=True)
    )
    pending_incoming = set(
        ConnectionRequest.objects
        .filter(receiver=request.user, sender_id__in=candidate_user_ids, status="pending")
        .values_list("sender_id", flat=True)
    )

    scored_cards = []
    for card in candidates:
        shared = matching_attributes(profile, card)

        # Core Discover rule: show every person sharing at least one of
        # college/course/year/city. An explicitly selected filter simply narrows
        # that pool; it never lowers the ranking of the remaining matches.
        if not shared:
            continue

        if card.user_id in active_match_user_ids:
            relation_status = "matched"
        elif card.user_id in pending_outgoing:
            relation_status = "pending"
        elif card.user_id in pending_incoming:
            relation_status = "incoming"
        else:
            relation_status = "available"

        scored_cards.append({
            "profile": card,
            "compatibility": min(100, 60 + len(shared) * 10),
            "match_count": len(shared),
            "matching_attributes": shared,
            "relation_status": relation_status,
        })

    scored_cards.sort(
        key=lambda item: (
            -item["match_count"],
            -item["compatibility"],
            item["profile"].display_name.casefold(),
        )
    )

    # Do not artificially cap Discover. The user asked to see all matching
    # people, with the strongest overlap first.
    cards = scored_cards

    return render(
        request,
        "discover.html",
        {
            "cards": cards,
            "colleges": College.objects.all().order_by("name"),
            "filters": filters,
        },
    )


@login_required
@require_POST
def discovery_action(request):
    target = get_object_or_404(StudentProfile, id=request.POST.get("profile_id"))
    action = request.POST.get("action")

    if target.user_id == request.user.id:
        flash.error(request, "You can't do that with your own profile.")
        return redirect("discover")

    if action == "connect":
        response = send_profile_match(request, target.user_id)
        # send_profile_match returns JSON for AJAX. Discover can remain a regular
        # form POST, so preserve the original page when it redirects.
        if wants_json(request):
            return response
        return redirect(request.POST.get("next") or "discover")

    if action == "save":
        SavedProfile.objects.get_or_create(user=request.user, profile=target)
        flash.success(request, "Profile saved for later.")
    elif action == "skip":
        SkippedProfile.objects.get_or_create(user=request.user, profile=target)
        flash.info(request, "We'll keep your discovery feed fresh.")
    elif action == "block":
        BlockedUser.objects.get_or_create(blocker=request.user, blocked=target.user)
        sever_relationship(request.user, target.user)
        flash.success(request, "Profile blocked and hidden.")

    return redirect(request.POST.get("next") or "discover")


# ---------------------------------------------------------------------------
# Connections & matches
# ---------------------------------------------------------------------------

@login_required
def connections(request):
    # Incoming match requests live on the Matches page. Connections keeps
    # outgoing pending requests and saved profiles.
    incoming = ConnectionRequest.objects.none()
    outgoing = (
        ConnectionRequest.objects
        .filter(sender=request.user, status="pending")
        .select_related("receiver", "receiver__student_profile")
        .order_by("-created_at")
    )
    saved = (
        SavedProfile.objects
        .filter(user=request.user)
        .select_related("profile", "profile__user")
    )
    return render(request, "connections.html", {
        "incoming": incoming,
        "outgoing": outgoing,
        "saved": saved,
    })


@login_required
@require_POST
def connection_action(request):
    connection = get_object_or_404(
        ConnectionRequest, id=request.POST.get("request_id")
    )
    action = request.POST.get("action")

    if (
        action == "accept"
        and connection.receiver_id == request.user.id
        and connection.status == "pending"
    ):
        if is_blocked(connection.sender, connection.receiver):
            return match_request_response(
                request, success=False, status="blocked",
                message="You can't accept this request.", fallback="matches",
            )

        with transaction.atomic():
            connection.status = "accepted"
            connection.save(update_fields=["status"])

            a, b = sorted([connection.sender_id, connection.receiver_id])
            match, _ = Match.objects.get_or_create(
                user_a_id=a, user_b_id=b
            )
            conversation = create_match_conversation(match)

        notify(
            connection.sender,
            "match",
            f"{request.user.get_full_name() or request.user.username} accepted your match request!",
            reverse("chat", args=[conversation.id]),
        )

        other_profile = get_profile(connection.sender)
        current_profile = get_profile(request.user)

        return match_request_response(
            request, success=True, status="accepted",
            message="You're matched! Your private chat is ready.",
            extra={
                "request_id": connection.id,
                "match_id": match.id,
                "conversation_id": conversation.id,
                "chat_url": reverse("chat", args=[conversation.id]),
                "unmatch_url": reverse("unmatch", args=[match.id]),
                "other_user_id": connection.sender_id,
                "profile_url": reverse("user_profile", args=[connection.sender_id]),
                "other_name": connection.sender.get_full_name() or connection.sender.username,
                "course": other_profile.course or "",
                "college": other_profile.college.name if other_profile.college else "",
                "compatibility": compatibility(current_profile, other_profile),
                "avatar_url": other_profile.primary_photo.image.url if other_profile.primary_photo else "",
            },
            fallback="matches",
        )

    if (
        action == "reject"
        and connection.receiver_id == request.user.id
        and connection.status == "pending"
    ):
        connection.status = "rejected"
        connection.save(update_fields=["status"])
        return match_request_response(
            request, success=True, status="rejected",
            message="Match request rejected.",
            extra={"request_id": connection.id}, fallback="matches",
        )

    if (
        action == "cancel"
        and connection.sender_id == request.user.id
        and connection.status == "pending"
    ):
        connection.status = "cancelled"
        connection.save(update_fields=["status"])
        return match_request_response(
            request, success=True, status="cancelled",
            message="Match request cancelled.",
            extra={"request_id": connection.id}, fallback="connections",
        )

    return match_request_response(
        request, success=False, status="invalid",
        message="This request is no longer available.", fallback="matches",
    )


@login_required
def matches(request):
    recent_requests = (
        ConnectionRequest.objects
        .filter(receiver=request.user, status="pending")
        .select_related("sender", "sender__student_profile")
        .order_by("-created_at")
    )

    match_qs = (
        Match.objects
        .filter(Q(user_a=request.user) | Q(user_b=request.user))
        .select_related(
            "user_a", "user_b",
            "user_a__student_profile",
            "user_b__student_profile",
        )
        .order_by("-created_at")
    )

    profile = get_profile(request.user)
    cards = []

    for match in match_qs:
        other_user = match.other(request.user)
        other_profile = get_profile(other_user)
        conversation = create_match_conversation(match)

        cards.append({
            "match": match,
            "profile": other_profile,
            "other_user": other_user,
            "conversation": conversation,
            "compatibility": compatibility(profile, other_profile),
        })

    return render(
        request,
        "matches.html",
        {
            "recent_requests": recent_requests,
            "cards": cards,
        },
    )


@login_required
@require_POST
def unmatch(request, match_id):
    match = get_object_or_404(Match, id=match_id)

    if request.user.id not in (match.user_a_id, match.user_b_id):
        if wants_json(request):
            return JsonResponse({"success": False, "message": "Not allowed."}, status=403)
        return redirect("matches")

    with transaction.atomic():
        conversation = Conversation.objects.filter(
            match=match, study_group__isnull=True
        ).first()

        if conversation:
            conversation.delete()

        # Re-use this same pair for future requests. After unmatching,
        # the next Match click starts again as PENDING.
        ConnectionRequest.objects.filter(
            Q(sender_id=match.user_a_id, receiver_id=match.user_b_id)
            | Q(sender_id=match.user_b_id, receiver_id=match.user_a_id),
            status="accepted",
        ).update(status="rejected")

        match.delete()

    if wants_json(request):
        return JsonResponse({
            "success": True,
            "status": "unmatched",
            "message": "Unmatched. You can send a new Match request again.",
            "match_id": match_id,
        })

    flash.info(request, "Unmatched. You can send a new Match request again.")
    return redirect("matches")
# ---------------------------------------------------------------------------
# Messaging
# ---------------------------------------------------------------------------

@login_required
def messages_view(request):
    conversations = (
        Conversation.objects
        .filter(
            members__user=request.user,
            study_group__isnull=True,
            match__isnull=False,
        )
        .select_related("match")
        .prefetch_related("members__user", "messages")
        .order_by("-updated_at")
    )

    unique_rows = {}

    for conversation in conversations:
        match = conversation.match

        if not match or request.user.id not in {match.user_a_id, match.user_b_id}:
            continue

        other_member = conversation.members.exclude(user=request.user).select_related("user").first()

        if not other_member:
            continue

        other_user = other_member.user
        last_message = conversation.messages.order_by("-created_at").first()
        activity_time = last_message.created_at if last_message else conversation.updated_at
        unread = conversation.messages.filter(
            read_at__isnull=True
        ).exclude(sender=request.user).count()

        row = {
            "conversation": conversation,
            "other_user": other_user,
            "last_message": last_message,
            "unread": unread,
            "activity_time": activity_time,
        }

        existing = unique_rows.get(other_user.id)

        if existing is None or activity_time > existing["activity_time"]:
            unique_rows[other_user.id] = row

    rows = sorted(
        unique_rows.values(),
        key=lambda row: row["activity_time"],
        reverse=True,
    )

    return render(request, "messages.html", {"rows": rows})


@login_required
def chat(request, conversation_id):
    conversation = get_object_or_404(
        Conversation.objects.select_related("match"),
        id=conversation_id,
        members__user=request.user,
        study_group__isnull=True,
        match__isnull=False,
    )

    match = conversation.match

    if request.user.id not in {match.user_a_id, match.user_b_id}:
        return redirect("messages")

    if is_blocked(request.user, match.other(request.user)):
        flash.error(request, "This conversation isn't available.")
        return redirect("messages")

    other_member = conversation.members.exclude(user=request.user).select_related("user").first()
    msgs = conversation.messages.select_related("sender").order_by("created_at")

    msgs.filter(
        read_at__isnull=True
    ).exclude(sender=request.user).update(read_at=timezone.now())

    return render(request, "chat.html", {
        "conversation": conversation,
        "other_user": other_member.user if other_member else None,
        "messages_list": msgs,
    })


@login_required
@require_POST
def send_message(request, conversation_id):
    conversation = get_object_or_404(
        Conversation.objects.select_related("match"),
        id=conversation_id,
        members__user=request.user,
        study_group__isnull=True,
        match__isnull=False,
    )

    match = conversation.match

    if request.user.id not in {match.user_a_id, match.user_b_id}:
        return redirect("messages")

    if is_blocked(request.user, match.other(request.user)):
        flash.error(request, "This conversation isn't available.")
        return redirect("messages")

    body = request.POST.get("body", "").strip()

    if body:
        Message.objects.create(
            conversation=conversation,
            sender=request.user,
            body=body,
        )
        conversation.save(update_fields=["updated_at"])
        notify_new_message(conversation, request.user, match.other(request.user))

    return redirect("chat", conversation_id=conversation.id)

# ---------------------------------------------------------------------------
# StudyMatch
# ---------------------------------------------------------------------------
@login_required
def studymatch(request):
    groups = StudyGroup.objects.select_related("owner").prefetch_related("members__user")

    my_group_ids = set(
        StudyGroupMember.objects
        .filter(user=request.user)
        .values_list("group_id", flat=True)
    )

    incoming_requests = StudyRequest.objects.filter(
        receiver=request.user,
        status="pending"
    ).select_related("sender")

    for group in groups:
        conversation, created = Conversation.objects.get_or_create(
            study_group=group
        )

        for member in group.members.select_related("user").all():
            ConversationMember.objects.get_or_create(
                conversation=conversation,
                user=member.user,
            )

    return render(
        request,
        "studymatch.html",
        {
            "groups": groups,
            "my_group_ids": my_group_ids,
            "incoming_requests": incoming_requests,
        },
    )

@login_required
def study_group_detail(request, group_id):
    group = get_object_or_404(
        StudyGroup.objects.prefetch_related("members__user__student_profile"),
        id=group_id,
    )

    is_member = StudyGroupMember.objects.filter(
        group=group,
        user=request.user,
    ).exists()

    is_owner = group.owner_id == request.user.id
    is_full = group.members.count() >= group.max_members

    relations = ConnectionRequest.objects.filter(Q(sender=request.user) | Q(receiver=request.user)).exclude(status__in=["cancelled", "rejected"]).values_list("sender_id", "receiver_id")
    connected_ids = {item for pair in relations for item in pair}

    return render(
        request,
        "study_group_detail.html",
        {
            "group": group,
            "is_member": is_member,
            "is_owner": is_owner,
            "is_full": is_full,
            "connected_ids": connected_ids,
        },
    )


@login_required
@require_POST
def remove_study_group_member(request, group_id, user_id):
    group = get_object_or_404(StudyGroup, id=group_id)

    if group.owner_id != request.user.id:
        flash.error(request, "Only the group owner can remove members.")
        return redirect("study_group_detail", group_id=group.id)

    if int(user_id) == group.owner_id:
        flash.error(request, "The group owner can't be removed.")
        return redirect("study_group_detail", group_id=group.id)

    deleted, _ = StudyGroupMember.objects.filter(group=group, user_id=user_id).delete()
    if deleted:
        flash.success(request, "Member removed from the group.")
    return redirect("study_group_detail", group_id=group.id)


@login_required
def study_group_call(request, group_id):
    group = get_object_or_404(StudyGroup, id=group_id)

    is_member = StudyGroupMember.objects.filter(group=group, user=request.user).exists()
    if not is_member:
        flash.error(request, "You must be a member of this study group to join the call.")
        return redirect("study_group_detail", group_id=group.id)

    return render(request, "study_group_call.html", {
        "group": group,
        "is_owner": group.owner_id == request.user.id,
    })


@login_required
@require_POST
def create_study_group(request):
    form = StudyGroupForm(request.POST)
    if form.is_valid():
        group = StudyGroup.objects.create(
            owner=request.user,
            **form.cleaned_data
        )
        StudyGroupMember.objects.get_or_create(
            group=group,
            user=request.user
        )
        flash.success(request, "Study group created.")
    else:
        flash.error(request, "Please check the study group details and try again.")
    return redirect("studymatch")


@login_required
@require_POST
def join_study_group(request, group_id):
    with transaction.atomic():
        # Lock the group row so two simultaneous joins can't both slip in
        # under the max_members check (prevents overbooking the last seat).
        group = get_object_or_404(StudyGroup.objects.select_for_update(), id=group_id)

        if StudyGroupMember.objects.filter(group=group, user=request.user).exists():
            flash.info(request, f"You're already in {group.name}.")
            return redirect("studymatch")

        current_count = StudyGroupMember.objects.select_for_update().filter(group=group).count()

        if current_count >= group.max_members:
            flash.error(request, "This study group is already full.")
        else:
            StudyGroupMember.objects.create(group=group, user=request.user)
            flash.success(request, f"You joined {group.name}.")

    return redirect("studymatch")


@login_required
@require_POST
def delete_study_group(request, group_id):
    group = get_object_or_404(StudyGroup, id=group_id)

    if group.owner_id != request.user.id:
        flash.error(request, "Only the group owner can delete this study group.")
        return redirect("study_group_detail", group_id=group.id)

    group.delete()

    flash.success(request, "Study group has been deleted.")
    return redirect("studymatch")

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@login_required
def event_detail(request, event_id):
    event = get_object_or_404(
        Event.objects.select_related("organizer", "college").prefetch_related("rsvps__user__student_profile__photos"),
        id=event_id,
    )

    is_rsvped = EventRSVP.objects.filter(
        event=event,
        user=request.user,
    ).exists()

    relations = ConnectionRequest.objects.filter(Q(sender=request.user) | Q(receiver=request.user)).exclude(status__in=["cancelled", "rejected"]).values_list("sender_id", "receiver_id")
    connected_ids = {item for pair in relations for item in pair}
    match_pairs = Match.objects.filter(Q(user_a=request.user) | Q(user_b=request.user)).values_list("user_a_id", "user_b_id")
    for a, b in match_pairs:
        connected_ids.update([a, b])

    return render(
        request,
        "event_detail.html",
        {
            "event": event,
            "is_rsvped": is_rsvped,
            "connected_ids": connected_ids,
            "visible_rsvps": [r for r in event.rsvps.all() if r.user_id == request.user.id or r.user_id == event.organizer_id or getattr(getattr(r.user, "settings", None), "allow_event_visibility", True)],
        },
    )
@login_required
def events(request):
    upcoming = Event.objects.filter(date__gte=date.today()).select_related("organizer", "college").prefetch_related("rsvps__user__student_profile__photos")
    my_rsvp_ids = set(EventRSVP.objects.filter(user=request.user).values_list("event_id", flat=True))
    return render(request, "events.html", {"events": upcoming, "my_rsvp_ids": my_rsvp_ids, "form": EventForm()})


@login_required
@require_POST
def create_event(request):
    form = EventForm(request.POST, request.FILES)
    if form.is_valid():
        event = form.save(commit=False)
        event.organizer = request.user
        event.save()
        EventRSVP.objects.get_or_create(event=event, user=request.user)
        flash.success(request, "Event created and published to campus.")
    else:
        flash.error(request, "Please check the event details and try again.")
    return redirect("events")


@login_required
@require_POST
def rsvp_event(request, event_id):
    with transaction.atomic():
        event = get_object_or_404(Event.objects.select_for_update(), id=event_id)
        existing = EventRSVP.objects.filter(event=event, user=request.user).first()

        if existing:
            existing.delete()
            flash.info(request, "RSVP removed.")
        elif event.rsvps.count() >= event.max_attendees:
            flash.error(request, "This event has reached its attendee limit.")
        else:
            EventRSVP.objects.create(event=event, user=request.user)
            flash.success(request, f"You're going to {event.title}!")

    return redirect("events")


@login_required
@require_POST
def delete_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)

    if event.organizer != request.user:
        flash.error(request, "You can only delete events you created.")
        return redirect("event_detail", event_id=event.id)

    event.delete()

    flash.success(request, "Your event has been deleted.")
    return redirect("events")


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------

@login_required
def feed(request):
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            flash.success(request, "Posted to the campus feed.")
            return redirect("feed")
        flash.error(request, "Please add some text or a valid image to your post.")
    blocked_ids = BlockedUser.objects.filter(blocker=request.user).values_list("blocked_id", flat=True)
    blocked_by_ids = BlockedUser.objects.filter(blocked=request.user).values_list("blocker_id", flat=True)
    posts = (
        Post.objects.filter(hidden=False)
        .exclude(author_id__in=blocked_ids)
        .exclude(author_id__in=blocked_by_ids)
        .select_related("author", "author__student_profile")
        .prefetch_related("likes", "comments__author__student_profile__photos")
    )
    liked_ids = set(Like.objects.filter(user=request.user).values_list("post_id", flat=True))
    relations = ConnectionRequest.objects.filter(Q(sender=request.user) | Q(receiver=request.user)).exclude(status__in=["cancelled", "rejected"]).values_list("sender_id", "receiver_id")
    connected_ids = {item for pair in relations for item in pair}
    match_pairs = Match.objects.filter(Q(user_a=request.user) | Q(user_b=request.user)).values_list("user_a_id", "user_b_id")
    for a, b in match_pairs:
        connected_ids.update([a, b])
    return render(request, "feed.html", {
        "posts": posts, "form": PostForm(), "comment_form": CommentForm(), "liked_ids": liked_ids,
        "connected_ids": connected_ids,
    })


@login_required
@require_POST
def like_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    if is_blocked(request.user, post.author):
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"error": "not allowed"}, status=403)
        flash.error(request, "You can't interact with this post.")
        return redirect(request.POST.get("next") or "feed")
    like, created = Like.objects.get_or_create(post=post, user=request.user)
    if not created:
        like.delete()
    elif post.author_id != request.user.id:
        notify(post.author, "like", f"{request.user.get_full_name() or request.user.username} liked your post.", reverse("post_detail", args=[post.id]))

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"liked": created, "count": post.likes.count()})
    return redirect(request.POST.get("next") or "feed")



@login_required
@require_POST
def delete_comment(request, comment_id):
    comment = get_object_or_404(Comment, id=comment_id)

    if comment.author_id != request.user.id:
        if wants_json(request):
            return JsonResponse({"success": False, "message": "You can only delete your own comments."}, status=403)
        flash.error(request, "You can only delete your own comments.")
        return redirect(request.POST.get("next") or "feed")

    post_id = comment.post_id
    comment.delete()

    if wants_json(request):
        return JsonResponse({
            "success": True,
            "comment_id": comment_id,
            "count": Comment.objects.filter(post_id=post_id).count(),
        })

    flash.success(request, "Your comment has been deleted.")
    return redirect(request.POST.get("next") or f"{reverse('feed')}#post-{post_id}")

@login_required
@require_POST
def delete_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)

    if post.author_id != request.user.id:
        flash.error(request, "You can only delete your own posts.")
        return redirect("feed")

    post.delete()

    flash.success(request, "Your post has been deleted.")
    return redirect("feed")


@login_required
@require_POST
def comment_post(request, post_id):
    post = get_object_or_404(Post, id=post_id)
    if is_blocked(request.user, post.author):
        if wants_json(request):
            return JsonResponse({"success": False, "message": "You can't interact with this post."}, status=403)
        flash.error(request, "You can't interact with this post.")
        return redirect(request.POST.get("next") or "feed")

    form = CommentForm(request.POST)
    if not form.is_valid():
        if wants_json(request):
            return JsonResponse({"success": False, "message": "Please enter a comment."}, status=400)
        flash.error(request, "Please enter a comment.")
        return redirect(request.POST.get("next") or "feed")

    comment = Comment.objects.create(
        post=post,
        author=request.user,
        body=form.cleaned_data["body"],
    )

    author_profile = get_profile(request.user)
    photo = author_profile.primary_photo

    if post.author_id != request.user.id:
        notify(
            post.author, "comment",
            f"{request.user.get_full_name() or request.user.username} commented on your post.",
            reverse("post_detail", args=[post.id]) + f"?comment={comment.id}#comment-{comment.id}",
        )

    if wants_json(request):
        return JsonResponse({
            "success": True,
            "comment_id": comment.id,
            "body": comment.body,
            "author_name": request.user.get_full_name() or request.user.username,
            "author_initial": (request.user.first_name or request.user.username or "S")[0].upper(),
            "author_photo_url": photo.image.url if photo else "",
            "count": post.comments.count(),
        })

    flash.success(request, "Comment added.")
    return redirect(request.POST.get("next") or f"{reverse('feed')}#post-{post.id}")


@login_required
def post_detail(request, post_id):
    post = get_object_or_404(Post.objects.select_related("author", "author__student_profile").prefetch_related("comments__author"), id=post_id)

    if is_blocked(request.user, post.author):
        flash.error(request, "This post isn't available.")
        return redirect("feed")

    relations = ConnectionRequest.objects.filter(Q(sender=request.user) | Q(receiver=request.user)).exclude(status__in=["cancelled", "rejected"]).values_list("sender_id", "receiver_id")
    connected_ids = {item for pair in relations for item in pair}
    match_pairs = Match.objects.filter(Q(user_a=request.user) | Q(user_b=request.user)).values_list("user_a_id", "user_b_id")
    for a, b in match_pairs:
        connected_ids.update([a, b])

    return render(request, "post_detail.html", {
        "post": post,
        "liked": Like.objects.filter(post=post, user=request.user).exists(),
        "comment_form": CommentForm(),
        "connected_ids": connected_ids,
        "highlight_comment_id": request.GET.get("comment"),
    })


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@login_required
def notifications(request):
    items = Notification.objects.filter(recipient=request.user)
    return render(request, "notifications.html", {"notifications": items})


@login_required
def open_notification(request, notification_id):
    note = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    if not note.read:
        note.read = True
        note.save(update_fields=["read"])
    return redirect(note.link or "notifications")


@login_required
@require_POST
def mark_notifications_read(request):
    Notification.objects.filter(recipient=request.user, read=False).update(read=True)
    return redirect("notifications")


@login_required
def search(request):
    query = request.GET.get("q", "").strip()
    results = []

    if query:
        blocked_ids = BlockedUser.objects.filter(blocker=request.user).values_list("blocked_id", flat=True)
        blocked_by_ids = BlockedUser.objects.filter(blocked=request.user).values_list("blocker_id", flat=True)

        matched_pairs = Match.objects.filter(
            Q(user_a=request.user) | Q(user_b=request.user)
        ).values_list("user_a_id", "user_b_id")
        matched_user_ids = {user_id for pair in matched_pairs for user_id in pair}
        matched_user_ids.discard(request.user.id)

        candidates = (
            StudentProfile.objects
            .filter(user_id__in=matched_user_ids)
            .exclude(user_id__in=blocked_ids)
            .exclude(user_id__in=blocked_by_ids)
            .select_related("user", "college")
            .prefetch_related("photos")
        )

        # Support both simple searches ("priyanshu") and full display-name
        # searches ("priyanshu pal"). Every entered word must occur in at
        # least one searchable name field.
        for token in query.split():
            candidates = candidates.filter(
                Q(user__first_name__icontains=token)
                | Q(user__last_name__icontains=token)
                | Q(user__username__icontains=token)
                | Q(user__email__icontains=token)
            )

        results = list(candidates.order_by("user__first_name", "user__last_name")[:25])

    return render(request, "search.html", {"query": query, "results": results})


# ---------------------------------------------------------------------------
# Settings & safety
# ---------------------------------------------------------------------------

@login_required
def settings_view(request):
    user_settings, _ = UserSettings.objects.get_or_create(user=request.user)
    profile = get_profile(request.user)
    # These five live on StudentProfile: it is the single source of truth the
    # rest of the app (Campus Cards, profile pages, study groups) reads.
    profile_fields = ["discoverable", "show_age", "show_college", "show_online", "allow_study_requests"]
    # These two exist only on UserSettings.
    settings_fields = ["profile_visible", "allow_event_visibility"]
    if request.method == "POST":
        for field in profile_fields:
            setattr(profile, field, request.POST.get(field) == "on")
        for field in settings_fields:
            setattr(user_settings, field, request.POST.get(field) == "on")
        profile.save(update_fields=profile_fields)
        user_settings.save(update_fields=settings_fields)
        flash.success(request, "Your privacy settings were updated.")
        return redirect("settings")
    return render(request, "settings.html", {"user_settings": user_settings, "profile": profile})


@login_required
def safety(request):
    blocked = BlockedUser.objects.filter(blocker=request.user).select_related("blocked")
    return render(request, "safety.html", {"blocked": blocked, "form": ReportForm()})


@login_required
@require_POST
def unblock_user(request, user_id):
    deleted, _ = BlockedUser.objects.filter(blocker=request.user, blocked_id=user_id).delete()
    if deleted:
        flash.success(request, "Profile unblocked.")
    return redirect("safety")


@login_required
@require_POST
def report(request):
    form = ReportForm(request.POST)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.reporter = request.user
        target_username = request.POST.get("target_username", "").strip()
        if target_username:
            from django.contrib.auth.models import User
            obj.target_user = User.objects.filter(username__iexact=target_username).first()
        obj.save()
        flash.success(request, "Thanks — our safety team will review this report.")
    else:
        flash.error(request, "Please choose a reason before submitting your report.")
    return redirect("safety")

@login_required
def study_group_chat(request, group_id):
    group = get_object_or_404(StudyGroup, id=group_id)

    # Only group members can access the group chat
    is_member = StudyGroupMember.objects.filter(
        group=group,
        user=request.user,
    ).exists()

    if not is_member:
        flash.error(request, "You must be a member of this study group.")
        return redirect("study_group_detail", group_id=group.id)

    conversation, created = Conversation.objects.get_or_create(
        study_group=group
    )

    # Make sure all current group members are in the conversation
    for member in group.members.select_related("user").all():
        ConversationMember.objects.get_or_create(
            conversation=conversation,
            user=member.user,
        )

    chat_messages = conversation.messages.select_related("sender").all()

    return render(
        request,
        "study_group_chat.html",
        {
            "group": group,
            "conversation": conversation,
            "chat_messages": chat_messages,
        },
    )


@login_required
@require_POST
def delete_study_group_message(request, message_id):
    message = get_object_or_404(
        Message,
        id=message_id,
        conversation__study_group__isnull=False,
    )

    if message.sender_id != request.user.id:
        flash.error(request, "You can only delete your own messages.")
        return redirect("study_group_chat", group_id=message.conversation.study_group_id)

    group_id = message.conversation.study_group_id
    message.delete()

    flash.success(request, "Your message has been deleted.")
    return redirect("study_group_chat", group_id=group_id)


@login_required
@require_POST
def send_study_group_message(request, group_id):
    group = get_object_or_404(StudyGroup, id=group_id)

    # Only group members can send messages
    is_member = StudyGroupMember.objects.filter(
        group=group,
        user=request.user,
    ).exists()

    if not is_member:
        flash.error(request, "You must be a member of this study group.")
        return redirect("study_group_detail", group_id=group.id)

    conversation, created = Conversation.objects.get_or_create(
        study_group=group
    )

    body = request.POST.get("body", "").strip()
    attachment = request.FILES.get("attachment")

    if attachment:
        error = validate_upload(attachment, ALLOWED_ATTACHMENT_EXTENSIONS, MAX_ATTACHMENT_UPLOAD_BYTES)
        if error:
            flash.error(request, error)
            return redirect("study_group_chat", group_id=group.id)

    if body or attachment:
        Message.objects.create(
            conversation=conversation,
            sender=request.user,
            body=body,
            attachment=attachment,
        )

        conversation.save(update_fields=["updated_at"])

    return redirect("study_group_chat", group_id=group.id)
@login_required
def posts(request):
    if request.method == "POST":
        form = PostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = request.user
            post.save()
            return redirect("posts")
    else:
        form = PostForm()

    posts = (
        Post.objects
        .filter(hidden=False)
        .filter(author=request.user)
        .select_related("author", "author__student_profile")
        .prefetch_related("likes", "comments__author")
    )

    liked_ids = set(
        Like.objects.filter(
            user=request.user,
            post__in=posts
        ).values_list("post_id", flat=True)
    )

    return render(request, "posts.html", {
        "posts": posts,
        "form": form,
        "liked_ids": liked_ids,
        "comment_form": CommentForm(),
    })







