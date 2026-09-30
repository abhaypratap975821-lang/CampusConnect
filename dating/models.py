from django.db import models

# Create your models here.
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class College(TimeStamped):
    name = models.CharField(max_length=160)
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=80, default="India")
    email_domain = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return self.name


class Interest(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True)

    def __str__(self):
        return self.name


class StudentProfile(TimeStamped):
    LOOKING_FOR = [("dating", "Dating"), ("friendship", "Friendship"), ("study", "Study partner"), ("networking", "Networking")]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="student_profile")
    college = models.ForeignKey(College, on_delete=models.SET_NULL, null=True, blank=True, related_name="students")
    dob = models.DateField(null=True, blank=True)
    course = models.CharField(max_length=120, blank=True)
    department = models.CharField(max_length=120, blank=True)
    year = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(8)])
    city = models.CharField(max_length=80, blank=True)
    bio = models.TextField(max_length=600, blank=True)
    hobbies = models.CharField(max_length=300, blank=True)
    academic_interests = models.CharField(max_length=300, blank=True)
    personality_tags = models.CharField(max_length=240, blank=True)
    looking_for = models.JSONField(default=list, blank=True)
    interests = models.ManyToManyField(Interest, blank=True, related_name="profiles")
    discoverable = models.BooleanField(default=True)
    show_age = models.BooleanField(default=True)
    show_college = models.BooleanField(default=True)
    show_online = models.BooleanField(default=True)
    allow_study_requests = models.BooleanField(default=True)

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def age(self):
        if not self.dob:
            return None
        today = timezone.localdate()
        return today.year - self.dob.year - ((today.month, today.day) < (self.dob.month, self.dob.day))

    @property
    def completion(self):
        checks = [
            bool(self.primary_photo),
            bool(self.user.get_full_name()),
            bool(self.bio),
            bool(self.college),
            bool(self.course),
            bool(self.year),
            bool(self.city),
            bool(self.interests.exists()) if self.pk else False,
        ]
        return round(sum(checks) / len(checks) * 100)

    @property
    def primary_photo(self):
        return self.photos.filter(is_primary=True).first() or self.photos.order_by("created_at").first()

    def __str__(self):
        return self.display_name


class ProfilePhoto(TimeStamped):
    profile = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="profiles/%Y/%m/", validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])])
    is_primary = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.is_primary:
            ProfilePhoto.objects.filter(profile=self.profile, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)


class ConnectionRequest(TimeStamped):
    STATUS = [("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected"), ("cancelled", "Cancelled")]
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_connections")
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="received_connections")
    status = models.CharField(max_length=12, choices=STATUS, default="pending")
    super_connect = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["sender", "receiver"], name="unique_connection_direction")]
        indexes = [models.Index(fields=["receiver", "status"])]

    def __str__(self):
        return f"{self.sender} → {self.receiver} ({self.status})"


class Match(TimeStamped):
    user_a = models.ForeignKey(User, on_delete=models.CASCADE, related_name="matches_as_a")
    user_b = models.ForeignKey(User, on_delete=models.CASCADE, related_name="matches_as_b")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user_a", "user_b"], name="unique_match_pair")]

    def other(self, user):
        return self.user_b if self.user_a_id == user.id else self.user_a


class SavedProfile(TimeStamped):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_profiles")
    profile = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="saved_by")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "profile"], name="unique_saved_profile")]


class SkippedProfile(TimeStamped):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="skipped_profiles")
    profile = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="skipped_by")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "profile"], name="unique_skipped_profile")]


class BlockedUser(TimeStamped):
    blocker = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocks_created")
    blocked = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blocked_by")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["blocker", "blocked"], name="unique_block")]


class Report(TimeStamped):
    TYPES = [("user", "User"), ("post", "Post"), ("message", "Message"), ("event", "Event"), ("photo", "Profile photo")]
    REASONS = [("harassment", "Harassment"), ("spam", "Spam"), ("fake", "Fake profile"), ("inappropriate", "Inappropriate content"), ("scam", "Scam"), ("other", "Other")]
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reports_made")
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reports_received")
    object_type = models.CharField(max_length=12, choices=TYPES)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    reason = models.CharField(max_length=20, choices=REASONS)
    details = models.TextField(blank=True)
    resolved = models.BooleanField(default=False)


class Post(TimeStamped):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="posts")
    content = models.TextField(max_length=1200)
    image = models.ImageField(upload_to="posts/%Y/%m/", blank=True, null=True, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])])
    hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Post by {self.author} ({self.created_at:%Y-%m-%d})"


class Like(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="unique_post_like")]


class Comment(TimeStamped):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="comments")
    body = models.CharField(max_length=500)

    def __str__(self):
        return f"{self.author} on post #{self.post_id}"


class StudyGroup(TimeStamped):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_study_groups")
    name = models.CharField(max_length=120)
    subject = models.CharField(max_length=120)
    description = models.TextField(max_length=600)
    topics = models.CharField(max_length=300, blank=True, default="", help_text="Comma-separated topics")
    max_members = models.PositiveSmallIntegerField(default=8, validators=[MinValueValidator(2), MaxValueValidator(50)])
    study_goal = models.CharField(max_length=240, blank=True)
    schedule = models.CharField(max_length=160, blank=True)

    def __str__(self):
        return self.name

    @property
    def topic_list(self):
        return [t.strip() for t in self.topics.split(",") if t.strip()]


class StudyGroupMember(TimeStamped):
    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_memberships")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["group", "user"], name="unique_study_member")]


class StudyRequest(TimeStamped):
    STATUS = [("pending", "Pending"), ("accepted", "Accepted"), ("rejected", "Rejected")]
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_requests_sent")
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_requests_received")
    subject = models.CharField(max_length=120)
    status = models.CharField(max_length=12, choices=STATUS, default="pending")


class StudySession(TimeStamped):
    group = models.ForeignKey(StudyGroup, on_delete=models.CASCADE, related_name="sessions")
    scheduled_for = models.DateTimeField()
    location = models.CharField(max_length=160, blank=True)
    goal = models.CharField(max_length=240, blank=True)


class Event(TimeStamped):
    CATEGORIES = [(x, x.replace("-", " ").title()) for x in ["hackathon", "college-fest", "workshop", "seminar", "sports", "cultural", "movie-night", "tech"]]
    organizer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="events_created")
    college = models.ForeignKey(College, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    title = models.CharField(max_length=180)
    description = models.TextField(max_length=1200)
    category = models.CharField(max_length=30, choices=CATEGORIES, default="workshop")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=180)
    image = models.ImageField(upload_to="events/%Y/%m/", blank=True, null=True, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])])
    max_attendees = models.PositiveIntegerField(default=100)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return self.title


class EventRSVP(TimeStamped):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="rsvps")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="event_rsvps")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="unique_event_rsvp")]


class Conversation(TimeStamped):
    match = models.OneToOneField(Match, on_delete=models.CASCADE, null=True, blank=True, related_name="conversation")
    study_group = models.OneToOneField(StudyGroup, on_delete=models.CASCADE, null=True, blank=True, related_name="conversation")


class ConversationMember(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="conversations")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["conversation", "user"], name="unique_conversation_member")]


class Message(TimeStamped):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="messages_sent")
    body = models.TextField(max_length=2000)
    image = models.ImageField(upload_to="messages/%Y/%m/", blank=True, null=True, validators=[FileExtensionValidator(["jpg", "jpeg", "png", "webp"])])
    attachment = models.FileField(upload_to="messages/%Y/%m/", blank=True, null=True, validators=[FileExtensionValidator([
        "pdf", "jpg", "jpeg", "png", "webp",
        "doc", "docx", "ppt", "pptx", "xls", "xlsx", "txt",
        "mp4", "mov", "webm",
    ])])
    read_at = models.DateTimeField(null=True, blank=True)
    deleted = models.BooleanField(default=False)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender} in conversation #{self.conversation_id}"


class Notification(TimeStamped):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=50)
    text = models.CharField(max_length=240)
    link = models.CharField(max_length=200, blank=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} → {self.recipient}"


class UserSettings(TimeStamped):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="settings")
    profile_visible = models.BooleanField(default=True)
    show_age = models.BooleanField(default=True)
    show_college = models.BooleanField(default=True)
    show_online = models.BooleanField(default=True)
    allow_discovery = models.BooleanField(default=True)
    allow_study_requests = models.BooleanField(default=True)
    allow_event_visibility = models.BooleanField(default=True)
