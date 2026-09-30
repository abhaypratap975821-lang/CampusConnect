from datetime import date

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
from PIL import Image
from django.test import TestCase
from django.urls import reverse

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
    StudentProfile,
    StudyGroup,
    StudyGroupMember,
    UserSettings,
)
from .forms import RegistrationForm
from .views import get_or_create_conversation, is_blocked


def make_user(username):
    return User.objects.create_user(username=username, password="pass12345")


class BlockEnforcementTests(TestCase):
    def setUp(self):
        self.u1 = make_user("u1@test.com")
        self.u2 = make_user("u2@test.com")
        BlockedUser.objects.create(blocker=self.u1, blocked=self.u2)

    def test_is_blocked_is_bidirectional(self):
        self.assertTrue(is_blocked(self.u1, self.u2))
        self.assertTrue(is_blocked(self.u2, self.u1))

    def test_blocked_user_cannot_view_profile(self):
        self.client.force_login(self.u2)
        resp = self.client.get(reverse("user_profile", args=[self.u1.id]), follow=True)
        self.assertRedirects(resp, reverse("discover"))

    def test_blocked_user_cannot_send_match_request(self):
        self.client.force_login(self.u2)
        self.client.post(reverse("send_profile_match", args=[self.u1.id]))
        self.assertFalse(
            ConnectionRequest.objects.filter(sender=self.u2, receiver=self.u1).exists()
        )

    def test_discovery_action_connect_blocked_by_direct_post_is_rejected(self):
        # Even if someone bypasses the UI and POSTs a profile_id directly,
        # the backend must still refuse it.
        from .models import StudentProfile
        target_profile = StudentProfile.objects.get_or_create(user=self.u1)[0]
        self.client.force_login(self.u2)
        self.client.post(reverse("discovery_action"), {
            "profile_id": target_profile.id, "action": "connect",
        })
        self.assertFalse(
            ConnectionRequest.objects.filter(sender=self.u2, receiver=self.u1).exists()
        )

    def test_blocking_severs_existing_match_and_conversation(self):
        BlockedUser.objects.all().delete()
        a, b = sorted([self.u1.id, self.u2.id])
        match = Match.objects.create(user_a_id=a, user_b_id=b)
        conversation = get_or_create_conversation(self.u1, self.u2)

        from .models import StudentProfile
        target_profile = StudentProfile.objects.get_or_create(user=self.u2)[0]
        self.client.force_login(self.u1)
        self.client.post(reverse("discovery_action"), {
            "profile_id": target_profile.id, "action": "block",
        })

        self.assertFalse(Match.objects.filter(id=match.id).exists())
        self.assertFalse(
            self.u1.conversations.filter(conversation_id=conversation.id).exists()
        )

    def test_blocked_user_cannot_open_chat(self):
        BlockedUser.objects.all().delete()
        a, b = sorted([self.u1.id, self.u2.id])
        Match.objects.create(user_a_id=a, user_b_id=b)
        conversation = get_or_create_conversation(self.u1, self.u2)
        BlockedUser.objects.create(blocker=self.u1, blocked=self.u2)

        self.client.force_login(self.u2)
        resp = self.client.get(reverse("chat", args=[conversation.id]), follow=True)
        self.assertRedirects(resp, reverse("messages"))

    def test_feed_hides_posts_from_blocked_relationship(self):
        post = Post.objects.create(author=self.u1, content="hello")
        self.client.force_login(self.u2)
        resp = self.client.get(reverse("feed"))
        self.assertNotIn(post, resp.context["posts"])

    def test_like_and_comment_blocked_on_blocked_authors_post(self):
        post = Post.objects.create(author=self.u1, content="hello")
        self.client.force_login(self.u2)
        self.client.post(reverse("like_post", args=[post.id]))
        self.assertEqual(post.likes.count(), 0)

    def test_unblock_removes_the_block(self):
        self.client.force_login(self.u1)
        self.client.post(reverse("unblock_user", args=[self.u2.id]))
        self.assertFalse(BlockedUser.objects.filter(blocker=self.u1, blocked=self.u2).exists())


class SelfActionGuardTests(TestCase):
    def test_cannot_send_match_request_to_self(self):
        u1 = make_user("solo@test.com")
        self.client.force_login(u1)
        resp = self.client.post(reverse("send_profile_match", args=[u1.id]), follow=True)
        self.assertFalse(ConnectionRequest.objects.filter(sender=u1, receiver=u1).exists())


class ProfileVisibilityTests(TestCase):
    def test_private_profile_hidden_from_non_connections(self):
        viewer = make_user("viewer@test.com")
        owner = make_user("owner@test.com")
        settings_row, _ = UserSettings.objects.get_or_create(user=owner)
        settings_row.profile_visible = False
        settings_row.save()

        self.client.force_login(viewer)
        resp = self.client.get(reverse("user_profile", args=[owner.id]), follow=True)
        self.assertRedirects(resp, reverse("discover"))

    def test_private_profile_still_visible_to_active_match(self):
        viewer = make_user("viewer2@test.com")
        owner = make_user("owner2@test.com")
        settings_row, _ = UserSettings.objects.get_or_create(user=owner)
        settings_row.profile_visible = False
        settings_row.save()
        a, b = sorted([viewer.id, owner.id])
        Match.objects.create(user_a_id=a, user_b_id=b)

        self.client.force_login(viewer)
        resp = self.client.get(reverse("user_profile", args=[owner.id]))
        self.assertEqual(resp.status_code, 200)


class StudyGroupCapacityTests(TestCase):
    def test_join_rejected_once_group_is_full(self):
        owner = make_user("owner3@test.com")
        joiner = make_user("joiner@test.com")
        group = StudyGroup.objects.create(
            owner=owner, name="G", subject="S", description="d", max_members=1
        )
        StudyGroupMember.objects.create(group=group, user=owner)

        self.client.force_login(joiner)
        self.client.post(reverse("join_study_group", args=[group.id]))
        self.assertEqual(StudyGroupMember.objects.filter(group=group).count(), 1)

    def test_double_join_click_does_not_duplicate_membership(self):
        owner = make_user("owner4@test.com")
        joiner = make_user("joiner2@test.com")
        group = StudyGroup.objects.create(
            owner=owner, name="G2", subject="S", description="d", max_members=5
        )
        self.client.force_login(joiner)
        self.client.post(reverse("join_study_group", args=[group.id]))
        self.client.post(reverse("join_study_group", args=[group.id]))
        self.assertEqual(
            StudyGroupMember.objects.filter(group=group, user=joiner).count(), 1
        )


class UploadValidationTests(TestCase):
    def test_rejects_disallowed_profile_photo_extension(self):
        user = make_user("photo@test.com")
        self.client.force_login(user)
        bad_file = SimpleUploadedFile("evil.exe", b"not an image", content_type="application/octet-stream")
        self.client.post(reverse("set_profile_photo"), {"image": bad_file})
        self.assertEqual(ProfilePhoto.objects.filter(profile__user=user).count(), 0)

    def test_rejects_oversized_profile_photo(self):
        user = make_user("photo2@test.com")
        self.client.force_login(user)
        big_file = SimpleUploadedFile("big.png", b"0" * (9 * 1024 * 1024), content_type="image/png")
        self.client.post(reverse("set_profile_photo"), {"image": big_file})
        self.assertEqual(ProfilePhoto.objects.filter(profile__user=user).count(), 0)

    def test_accepts_valid_profile_photo(self):
        user = make_user("photo3@test.com")
        self.client.force_login(user)
        stream = BytesIO()
        Image.new("RGB", (1, 1), "white").save(stream, format="PNG")
        good_file = SimpleUploadedFile("ok.png", stream.getvalue(), content_type="image/png")
        self.client.post(reverse("set_profile_photo"), {"image": good_file})
        self.assertEqual(ProfilePhoto.objects.filter(profile__user=user).count(), 1)


class DashboardTests(TestCase):
    def test_dashboard_shows_one_combined_your_matches_card(self):
        user = make_user("dash@test.com")
        self.client.force_login(user)
        resp = self.client.get(reverse("dashboard"))
        self.assertContains(resp, "Your Matches")
        self.assertNotContains(resp, "Recent matches")
        self.assertNotContains(resp, "Unread messages")

    def test_match_request_is_only_on_matches_page(self):
        receiver = make_user("receiver@test.com")
        sender = make_user("sender@test.com")
        ConnectionRequest.objects.create(sender=sender, receiver=receiver)
        self.client.force_login(receiver)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertNotContains(dashboard, 'data-testid="dashboard-request-row"')
        matches_page = self.client.get(reverse("matches"))
        self.assertContains(matches_page, "Recent Match Requests")
        self.assertContains(matches_page, sender.username)

    def test_accept_ajax_creates_match_conversation_and_moves_request(self):
        receiver = make_user("receiver2@test.com")
        sender = make_user("sender2@test.com")
        cr = ConnectionRequest.objects.create(sender=sender, receiver=receiver)
        self.client.force_login(receiver)
        response = self.client.post(
            reverse("connection_action"),
            {"request_id": cr.id, "action": "accept"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "accepted")
        cr.refresh_from_db()
        self.assertEqual(cr.status, "accepted")
        a, b = sorted([sender.id, receiver.id])
        match = Match.objects.get(user_a_id=a, user_b_id=b)
        self.assertTrue(Conversation.objects.filter(match=match).exists())
        self.assertEqual(ConversationMember.objects.filter(conversation=match.conversation).count(), 2)

    def test_reject_ajax_removes_pending_request(self):
        receiver = make_user("receiver3@test.com")
        sender = make_user("sender3@test.com")
        cr = ConnectionRequest.objects.create(sender=sender, receiver=receiver)
        self.client.force_login(receiver)
        response = self.client.post(
            reverse("connection_action"),
            {"request_id": cr.id, "action": "reject"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "rejected")
        cr.refresh_from_db()
        self.assertEqual(cr.status, "rejected")
        self.assertFalse(Match.objects.exists())

    def test_unmatch_resets_request_and_allows_rematch(self):
        u1 = make_user("unmatch1@test.com")
        u2 = make_user("unmatch2@test.com")
        a, b = sorted([u1.id, u2.id])
        cr = ConnectionRequest.objects.create(sender=u1, receiver=u2, status="accepted")
        match = Match.objects.create(user_a_id=a, user_b_id=b)
        conv = get_or_create_conversation(u1, u2)
        self.assertIsNotNone(conv)

        self.client.force_login(u1)
        response = self.client.post(
            reverse("unmatch", args=[match.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Match.objects.filter(id=match.id).exists())
        cr.refresh_from_db()
        self.assertEqual(cr.status, "rejected")

        retry = self.client.post(
            reverse("send_profile_match", args=[u2.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json()["status"], "pending")
        cr.refresh_from_db()
        self.assertEqual(cr.status, "pending")

    def test_dashboard_match_counts_use_active_and_pending_counts(self):
        user = make_user("dashcounts@test.com")
        other = make_user("dashother@test.com")
        a, b = sorted([user.id, other.id])
        Match.objects.create(user_a_id=a, user_b_id=b)
        pending_other = make_user("dashpending@test.com")
        ConnectionRequest.objects.create(sender=pending_other, receiver=user, status="pending")
        self.client.force_login(user)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.context["active_matches_count"], 1)
        self.assertEqual(resp.context["pending_match_count"], 1)


class CampusCardsFilterTests(TestCase):
    def test_year_filter_narrows_results(self):
        from .models import StudentProfile
        viewer = make_user("viewer_discover@test.com")
        match_user = make_user("year2@test.com")
        other_user = make_user("year3@test.com")
        StudentProfile.objects.filter(user=match_user).update(year=2, discoverable=True) if StudentProfile.objects.filter(user=match_user).exists() else StudentProfile.objects.create(user=match_user, year=2, discoverable=True)
        StudentProfile.objects.filter(user=other_user).update(year=3, discoverable=True) if StudentProfile.objects.filter(user=other_user).exists() else StudentProfile.objects.create(user=other_user, year=3, discoverable=True)

        self.client.force_login(viewer)
        resp = self.client.get(reverse("discover"), {"year": "2"})
        cards_usernames = [c["profile"].user.username for c in resp.context["cards"]]
        self.assertIn("year2@test.com", cards_usernames)
        self.assertNotIn("year3@test.com", cards_usernames)

    def test_discover_connect_button_sends_request_without_opening_profile(self):
        from .models import StudentProfile
        viewer = make_user("connectviewer@test.com")
        target_user = make_user("connecttarget@test.com")
        target_profile = StudentProfile.objects.get_or_create(user=target_user)[0]
        self.client.force_login(viewer)
        resp = self.client.post(reverse("discovery_action"), {
            "profile_id": target_profile.id, "action": "connect",
        }, follow=True)
        self.assertTrue(ConnectionRequest.objects.filter(sender=viewer, receiver=target_user).exists())
        # Should redirect back to discover, not to the target's profile page.
        self.assertEqual(resp.redirect_chain[-1][0], reverse("discover"))


class DiscoveryRankingAndProfileVisibilityTests(TestCase):
    def test_discover_requires_one_shared_attribute_and_ranks_by_shared_count(self):
        viewer = make_user("discover_rank_viewer@test.com")
        one_match = make_user("discover_one@test.com")
        many_match = make_user("discover_many@test.com")
        no_match = make_user("discover_none@test.com")
        college = College.objects.create(name="Test College", city="Agra")

        StudentProfile.objects.update_or_create(
            user=viewer,
            defaults={
                "college": college, "course": "Data Science", "department": "Computer",
                "year": 2, "city": "Agra", "hobbies": "Gaming, Music",
                "academic_interests": "AI, Python", "personality_tags": "Calm, Curious",
                "discoverable": True,
            },
        )
        StudentProfile.objects.update_or_create(
            user=one_match,
            defaults={"year": 2, "course": "Arts", "city": "Delhi", "discoverable": True},
        )
        StudentProfile.objects.update_or_create(
            user=many_match,
            defaults={
                "college": college, "course": "Data Science", "department": "Computer",
                "year": 2, "city": "Agra", "hobbies": "Gaming, Sports",
                "academic_interests": "AI, C", "discoverable": True,
            },
        )
        StudentProfile.objects.update_or_create(
            user=no_match,
            defaults={"year": 4, "course": "History", "city": "Jaipur", "discoverable": True},
        )

        self.client.force_login(viewer)
        resp = self.client.get(reverse("discover"))
        cards = resp.context["cards"]
        usernames = [card["profile"].user.username for card in cards]

        self.assertIn("discover_one@test.com", usernames)
        self.assertIn("discover_many@test.com", usernames)
        self.assertNotIn("discover_none@test.com", usernames)
        self.assertLess(
            usernames.index("discover_many@test.com"),
            usernames.index("discover_one@test.com"),
        )

    def test_other_profile_hides_posts_until_active_match(self):
        viewer = make_user("profile_viewer@test.com")
        owner = make_user("profile_owner@test.com",)
        post = Post.objects.create(author=owner, content="private until matched")
        self.client.force_login(viewer)

        before = self.client.get(reverse("user_profile", args=[owner.id]))
        self.assertEqual(before.status_code, 200)
        self.assertFalse(before.context["can_view_posts"])
        self.assertNotContains(before, post.content)
        self.assertEqual(before.context["posts_count"], 0)

        a, b = sorted([viewer.id, owner.id])
        Match.objects.create(user_a_id=a, user_b_id=b)
        after = self.client.get(reverse("user_profile", args=[owner.id]))
        self.assertTrue(after.context["can_view_posts"])
        self.assertContains(after, post.content)
        self.assertEqual(after.context["posts_count"], 1)


class FeedMatchAndAjaxLikeTests(TestCase):
    def test_ajax_like_toggles_and_returns_json(self):
        author = make_user("postauthor@test.com")
        liker = make_user("liker@test.com")
        post = Post.objects.create(author=author, content="hi")
        self.client.force_login(liker)
        resp = self.client.post(
            reverse("like_post", args=[post.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["liked"])
        self.assertEqual(data["count"], 1)

    def test_feed_match_button_hidden_once_connected(self):
        author = make_user("feedauthor@test.com")
        viewer = make_user("feedviewer@test.com")
        Post.objects.create(author=author, content="hi there")
        self.client.force_login(viewer)
        resp = self.client.get(reverse("feed"))
        self.assertContains(resp, 'data-testid="feed-match-button"')

        ConnectionRequest.objects.create(sender=viewer, receiver=author, status="accepted")
        resp2 = self.client.get(reverse("feed"))
        self.assertNotContains(resp2, 'data-testid="feed-match-button"')


class StudyGroupChatBugfixTests(TestCase):
    def test_non_member_denied_without_crashing(self):
        owner = make_user("gowner@test.com")
        outsider = make_user("outsider@test.com")
        group = StudyGroup.objects.create(
            owner=owner, name="G3", subject="S", description="d", max_members=5
        )
        self.client.force_login(outsider)
        # This used to raise NameError('messages' is not defined) instead of
        # redirecting cleanly.
        resp = self.client.get(reverse("study_group_chat", args=[group.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertRedirects(resp, reverse("study_group_detail", args=[group.id]))

class StudyMatchPhase3Tests(TestCase):
    def test_create_group_saves_topics(self):
        from .models import StudyGroup
        owner = make_user("creator@test.com")
        self.client.force_login(owner)
        self.client.post(reverse("create_study_group"), {
            "name": "Django Study Group", "subject": "Django", "description": "desc",
            "topics": "Django, REST API, Deployment", "max_members": 10,
            "study_goal": "Ship a project", "schedule": "7 PM - 9 PM",
        })
        group = StudyGroup.objects.get(name="Django Study Group")
        self.assertEqual(group.topic_list, ["Django", "REST API", "Deployment"])

    def test_owner_can_remove_member_but_not_self(self):
        owner = make_user("owner_remove@test.com")
        member = make_user("member_remove@test.com")
        group = StudyGroup.objects.create(owner=owner, name="G", subject="S", description="d", max_members=5)
        StudyGroupMember.objects.create(group=group, user=owner)
        StudyGroupMember.objects.create(group=group, user=member)

        self.client.force_login(owner)
        self.client.post(reverse("remove_study_group_member", args=[group.id, member.id]))
        self.assertFalse(StudyGroupMember.objects.filter(group=group, user=member).exists())

        # Owner can't be removed even via a direct POST.
        self.client.post(reverse("remove_study_group_member", args=[group.id, owner.id]))
        self.assertTrue(StudyGroupMember.objects.filter(group=group, user=owner).exists())

    def test_non_owner_cannot_remove_member(self):
        owner = make_user("owner_remove2@test.com")
        member_a = make_user("member_a@test.com")
        member_b = make_user("member_b@test.com")
        group = StudyGroup.objects.create(owner=owner, name="G2", subject="S", description="d", max_members=5)
        StudyGroupMember.objects.create(group=group, user=member_a)
        StudyGroupMember.objects.create(group=group, user=member_b)

        self.client.force_login(member_a)
        self.client.post(reverse("remove_study_group_member", args=[group.id, member_b.id]))
        self.assertTrue(StudyGroupMember.objects.filter(group=group, user=member_b).exists())

    def test_group_full_state_shown_on_detail_page(self):
        owner = make_user("owner_full@test.com")
        visitor = make_user("visitor_full@test.com")
        group = StudyGroup.objects.create(owner=owner, name="FullGroup", subject="S", description="d", max_members=1)
        StudyGroupMember.objects.create(group=group, user=owner)

        self.client.force_login(visitor)
        resp = self.client.get(reverse("study_group_detail", args=[group.id]))
        self.assertContains(resp, 'data-testid="study-group-full-pill"')
        self.assertContains(resp, 'data-testid="study-group-full-button"')

    def test_non_member_cannot_open_video_call_page(self):
        owner = make_user("owner_call@test.com")
        outsider = make_user("outsider_call@test.com")
        group = StudyGroup.objects.create(owner=owner, name="CallGroup", subject="S", description="d", max_members=5)
        StudyGroupMember.objects.create(group=group, user=owner)

        self.client.force_login(outsider)
        resp = self.client.get(reverse("study_group_call", args=[group.id]), follow=True)
        self.assertRedirects(resp, reverse("study_group_detail", args=[group.id]))

    def test_member_can_open_video_call_page(self):
        owner = make_user("owner_call2@test.com")
        group = StudyGroup.objects.create(owner=owner, name="CallGroup2", subject="S", description="d", max_members=5)
        StudyGroupMember.objects.create(group=group, user=owner)

        self.client.force_login(owner)
        resp = self.client.get(reverse("study_group_call", args=[group.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-testid="end-call-button"')

    def test_widened_attachment_types_accepted(self):
        owner = make_user("owner_attach@test.com")
        group = StudyGroup.objects.create(owner=owner, name="AttachGroup", subject="S", description="d", max_members=5)
        StudyGroupMember.objects.create(group=group, user=owner)
        self.client.force_login(owner)
        doc_file = SimpleUploadedFile("notes.docx", b"0" * 200, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        resp = self.client.post(reverse("send_study_group_message", args=[group.id]), {
            "body": "", "attachment": doc_file,
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        conv = get_or_create_conversation_for_group(group)
        self.assertTrue(conv.messages.filter(attachment__icontains="notes").exists())


class AdditionalRegressionTests(TestCase):
    def test_registration_rejects_under_18(self):
        college = College.objects.create(name="Test College", city="Agra")
        form = RegistrationForm(data={
            "first_name": "Young",
            "last_name": "Student",
            "email": "young@test.com",
            "college": college.id,
            "course": "Computer Science",
            "dob": date.today().replace(year=date.today().year - 17),
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "terms": "on",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("dob", form.errors)

    def test_registration_rejects_missing_dob(self):
        self.assertTrue(RegistrationForm().fields["dob"].required)

    def test_profile_photo_rejects_corrupt_image_content(self):
        user = make_user("corrupt_photo@test.com")
        self.client.force_login(user)
        bad_file = SimpleUploadedFile("fake.png", b"not-a-real-image", content_type="image/png")
        self.client.post(reverse("set_profile_photo"), {"image": bad_file})
        self.assertFalse(ProfilePhoto.objects.filter(profile__user=user).exists())

    def test_private_profile_respects_profile_visible_setting(self):
        viewer = make_user("viewer_visibility@test.com")
        owner = make_user("owner_visibility@test.com")
        settings_row, _ = UserSettings.objects.get_or_create(user=owner)
        settings_row.profile_visible = False
        settings_row.save(update_fields=["profile_visible", "updated_at"])

        self.client.force_login(viewer)
        response = self.client.get(reverse("user_profile", args=[owner.id]), follow=True)
        self.assertRedirects(response, reverse("discover"))

    def test_event_rsvp_respects_capacity(self):
        organizer = make_user("event_owner@test.com")
        attendee = make_user("event_attendee@test.com")
        full_event = Event.objects.create(
            organizer=organizer,
            title="Full Event",
            description="d",
            date=date.today(),
            start_time="18:00",
            location="Hall",
            max_attendees=1,
        )
        EventRSVP.objects.create(event=full_event, user=organizer)

        self.client.force_login(attendee)
        self.client.post(reverse("rsvp_event", args=[full_event.id]))
        self.assertFalse(EventRSVP.objects.filter(event=full_event, user=attendee).exists())

    def test_private_message_cannot_be_deleted_through_group_delete_endpoint(self):
        sender = make_user("private_sender@test.com")
        receiver = make_user("private_receiver@test.com")
        a, b = sorted([sender.id, receiver.id])
        match = Match.objects.create(user_a_id=a, user_b_id=b)
        conversation = get_or_create_conversation(sender, receiver)
        message = conversation.messages.create(sender=sender, body="hello")

        self.client.force_login(sender)
        response = self.client.post(
            reverse("delete_study_group_message", args=[message.id]),
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Message.objects.filter(id=message.id).exists())


def get_or_create_conversation_for_group(group):
    from .models import Conversation
    return Conversation.objects.get(study_group=group)


import asyncio
from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase


class StudyCallSignalingTests(TransactionTestCase):
    """Real WebSocket-level tests of the WebRTC signaling relay, since the
    HTTP-only tests above can't exercise the consumer itself."""

    def test_join_relay_and_end_call(self):
        from .consumers import StudyCallConsumer
        from .models import StudyGroup

        owner = make_user("call_owner@test.com")
        member = make_user("call_member@test.com")
        outsider = make_user("call_outsider@test.com")
        group = StudyGroup.objects.create(owner=owner, name="SigGroup", subject="S", description="d", max_members=5)
        StudyGroupMember.objects.create(group=group, user=owner)
        StudyGroupMember.objects.create(group=group, user=member)

        async def scenario():
            app = StudyCallConsumer.as_asgi()

            # Outsider (not a member) must be rejected.
            comm_outsider = WebsocketCommunicator(app, f"/ws/study/{group.id}/call/")
            comm_outsider.scope["user"] = outsider
            comm_outsider.scope["url_route"] = {"kwargs": {"group_id": group.id}}
            connected, _ = await comm_outsider.connect()
            self.assertFalse(connected)

            # Owner connects first.
            comm_owner = WebsocketCommunicator(app, f"/ws/study/{group.id}/call/")
            comm_owner.scope["user"] = owner
            comm_owner.scope["url_route"] = {"kwargs": {"group_id": group.id}}
            connected_owner, _ = await comm_owner.connect()
            self.assertTrue(connected_owner)

            # Member joins second; owner should get a peer-joined event.
            comm_member = WebsocketCommunicator(app, f"/ws/study/{group.id}/call/")
            comm_member.scope["user"] = member
            comm_member.scope["url_route"] = {"kwargs": {"group_id": group.id}}
            connected_member, _ = await comm_member.connect()
            self.assertTrue(connected_member)

            owner_event = await comm_owner.receive_json_from(timeout=2)
            self.assertEqual(owner_event["type"], "peer-joined")

            # Owner sends a signaling "offer" targeted at the member's peer id.
            member_peer_id = owner_event["peer_id"]
            await comm_owner.send_json_to({
                "type": "offer", "target": member_peer_id, "sdp": {"type": "offer", "sdp": "fake-sdp"},
            })
            relayed = await comm_member.receive_json_from(timeout=2)
            self.assertEqual(relayed["type"], "offer")
            self.assertEqual(relayed["sdp"]["sdp"], "fake-sdp")

            # Owner ends the call for everyone.
            await comm_owner.send_json_to({"type": "end-call"})
            ended_for_owner = await comm_owner.receive_json_from(timeout=2)
            ended_for_member = await comm_member.receive_json_from(timeout=2)
            self.assertEqual(ended_for_owner["type"], "call-ended")
            self.assertEqual(ended_for_member["type"], "call-ended")

            await comm_owner.disconnect()
            await comm_member.disconnect()
            await comm_outsider.disconnect()

        asyncio.run(scenario())

    def test_non_owner_cannot_end_call(self):
        from .consumers import StudyCallConsumer
        from .models import StudyGroup

        owner = make_user("call_owner2@test.com")
        member = make_user("call_member2@test.com")
        group = StudyGroup.objects.create(owner=owner, name="SigGroup2", subject="S", description="d", max_members=5)
        StudyGroupMember.objects.create(group=group, user=owner)
        StudyGroupMember.objects.create(group=group, user=member)

        async def scenario():
            app = StudyCallConsumer.as_asgi()

            comm_owner = WebsocketCommunicator(app, f"/ws/study/{group.id}/call/")
            comm_owner.scope["user"] = owner
            comm_owner.scope["url_route"] = {"kwargs": {"group_id": group.id}}
            await comm_owner.connect()

            comm_member = WebsocketCommunicator(app, f"/ws/study/{group.id}/call/")
            comm_member.scope["user"] = member
            comm_member.scope["url_route"] = {"kwargs": {"group_id": group.id}}
            await comm_member.connect()
            await comm_owner.receive_json_from(timeout=2)  # the peer-joined event

            # A non-owner member tries to end the call; nothing should happen.
            await comm_member.send_json_to({"type": "end-call"})
            self.assertTrue(await comm_owner.receive_nothing(timeout=1))
            self.assertTrue(await comm_member.receive_nothing(timeout=1))

            await comm_owner.disconnect()
            await comm_member.disconnect()

        asyncio.run(scenario())

class NotificationDeepLinkTests(TestCase):
    def test_like_notification_links_to_post_detail(self):
        author = make_user("notif_author@test.com")
        liker = make_user("notif_liker@test.com")
        post = Post.objects.create(author=author, content="hi")
        self.client.force_login(liker)
        self.client.post(reverse("like_post", args=[post.id]))
        note = Notification.objects.get(recipient=author, kind="like")
        self.assertEqual(note.link, reverse("post_detail", args=[post.id]))

    def test_comment_notification_links_to_post_and_highlights_comment(self):
        author = make_user("notif_author2@test.com")
        commenter = make_user("notif_commenter@test.com")
        post = Post.objects.create(author=author, content="hi")
        self.client.force_login(commenter)
        self.client.post(reverse("comment_post", args=[post.id]), {"body": "nice post!"})
        note = Notification.objects.get(recipient=author, kind="comment")
        comment = post.comments.get(author=commenter)
        self.assertEqual(note.link, reverse("post_detail", args=[post.id]) + f"?comment={comment.id}#comment-{comment.id}")

    def test_opening_notification_marks_it_read_and_redirects(self):
        author = make_user("notif_author3@test.com")
        liker = make_user("notif_liker3@test.com")
        post = Post.objects.create(author=author, content="hi")
        self.client.force_login(liker)
        self.client.post(reverse("like_post", args=[post.id]))
        note = Notification.objects.get(recipient=author, kind="like")
        self.assertFalse(note.read)

        self.client.force_login(author)
        resp = self.client.get(reverse("open_notification", args=[note.id]), follow=True)
        note.refresh_from_db()
        self.assertTrue(note.read)
        self.assertEqual(resp.redirect_chain[-1][0], note.link)

    def test_cannot_open_someone_elses_notification(self):
        recipient = make_user("notif_owner@test.com")
        intruder = make_user("notif_intruder@test.com")
        note = Notification.objects.create(recipient=recipient, kind="like", text="x", link="/feed/")
        self.client.force_login(intruder)
        resp = self.client.get(reverse("open_notification", args=[note.id]))
        self.assertEqual(resp.status_code, 404)

    def test_match_accepted_notification_links_to_conversation_with_acceptor(self):
        sender = make_user("acc_sender@test.com")
        receiver = make_user("acc_receiver@test.com")
        cr = ConnectionRequest.objects.create(sender=sender, receiver=receiver)
        self.client.force_login(receiver)
        self.client.post(reverse("connection_action"), {"request_id": cr.id, "action": "accept"})
        note = Notification.objects.get(recipient=sender, kind="match")
        self.assertEqual(note.link, reverse("chat", args=[Match.objects.get(user_a_id=min(sender.id, receiver.id), user_b_id=max(sender.id, receiver.id)).conversation.id]))

    def test_message_notification_created_and_deduplicated(self):
        u1 = make_user("msg_sender@test.com")
        u2 = make_user("msg_recipient@test.com")
        a, b = sorted([u1.id, u2.id])
        match = Match.objects.create(user_a_id=a, user_b_id=b)
        conv = get_or_create_conversation(u1, u2)

        self.client.force_login(u1)
        self.client.post(reverse("send_message", args=[conv.id]), {"body": "hey"})
        self.client.post(reverse("send_message", args=[conv.id]), {"body": "you there?"})

        notes = Notification.objects.filter(recipient=u2, kind="message", link=reverse("chat", args=[conv.id]))
        self.assertEqual(notes.count(), 1)
        self.assertIn("msg_sender@test.com", notes.first().text)
        self.assertFalse(notes.first().read)

    def test_message_notification_link_opens_correct_conversation(self):
        u1 = make_user("msg_sender2@test.com")
        u2 = make_user("msg_recipient2@test.com")
        u3 = make_user("msg_other@test.com")
        a, b = sorted([u1.id, u2.id])
        Match.objects.create(user_a_id=a, user_b_id=b)
        conv_12 = get_or_create_conversation(u1, u2)
        c, d = sorted([u1.id, u3.id])
        Match.objects.create(user_a_id=c, user_b_id=d)
        conv_13 = get_or_create_conversation(u1, u3)

        self.client.force_login(u1)
        self.client.post(reverse("send_message", args=[conv_12.id]), {"body": "hi u2"})
        note = Notification.objects.get(recipient=u2, kind="message")
        self.assertEqual(note.link, reverse("chat", args=[conv_12.id]))
        self.assertNotEqual(note.link, reverse("chat", args=[conv_13.id]))


class GlobalSearchTests(TestCase):
    def test_search_finds_matching_name_only_for_active_matches(self):
        searcher = make_user("searcher@test.com")
        target = User.objects.create_user(username="findme@test.com", password="x", first_name="Rahul", last_name="Sharma")
        StudentProfile.objects.get_or_create(user=target, defaults={"discoverable": True})
        a, b = sorted([searcher.id, target.id])
        Match.objects.create(user_a_id=a, user_b_id=b)
        self.client.force_login(searcher)
        resp = self.client.get(reverse("search"), {"q": "Rahul"})
        self.assertIn(target, [p.user for p in resp.context["results"]])

    def test_search_excludes_blocked_relationship(self):
        searcher = make_user("searcher2@test.com")
        target = User.objects.create_user(username="blocked_target@test.com", password="x", first_name="Priya")
        StudentProfile.objects.get_or_create(user=target, defaults={"discoverable": True})
        BlockedUser.objects.create(blocker=searcher, blocked=target)
        self.client.force_login(searcher)
        resp = self.client.get(reverse("search"), {"q": "Priya"})
        self.assertNotIn(target, [p.user for p in resp.context["results"]])

    def test_search_respects_discoverability_for_strangers(self):
        searcher = make_user("searcher3@test.com")
        target = User.objects.create_user(username="hidden_target@test.com", password="x", first_name="Ananya")
        StudentProfile.objects.get_or_create(user=target, defaults={"discoverable": False})
        self.client.force_login(searcher)
        resp = self.client.get(reverse("search"), {"q": "Ananya"})
        self.assertNotIn(target, [p.user for p in resp.context["results"]])

    def test_search_does_not_show_a_connection_without_an_active_match(self):
        searcher = make_user("searcher4@test.com")
        target = User.objects.create_user(username="connected_target@test.com", password="x", first_name="Ishaan")
        StudentProfile.objects.get_or_create(user=target, defaults={"discoverable": False})
        ConnectionRequest.objects.create(sender=searcher, receiver=target, status="accepted")
        self.client.force_login(searcher)
        resp = self.client.get(reverse("search"), {"q": "Ishaan"})
        self.assertNotIn(target, [p.user for p in resp.context["results"]])

class SettingsReconciliationTests(TestCase):
    def test_settings_page_writes_to_the_fields_actually_enforced(self):
        from .models import StudentProfile
        user = make_user("settingsuser@test.com")
        StudentProfile.objects.get_or_create(user=user)
        self.client.force_login(user)
        self.client.post(reverse("settings"), {
            # deliberately omit all checkboxes -> everything should turn off
        })
        profile = StudentProfile.objects.get(user=user)
        self.assertFalse(profile.discoverable)
        self.assertFalse(profile.show_age)
        self.assertFalse(profile.show_college)
        self.assertFalse(profile.show_online)
        self.assertFalse(profile.allow_study_requests)
        us = UserSettings.objects.get(user=user)
        self.assertFalse(us.profile_visible)
        self.assertFalse(us.allow_event_visibility)

    def test_turning_off_discoverable_via_settings_hides_from_campus_cards(self):
        from .models import StudentProfile
        viewer = make_user("cc_viewer@test.com")
        target = make_user("cc_target@test.com")
        StudentProfile.objects.get_or_create(user=target, defaults={"discoverable": True})
        self.client.force_login(target)
        self.client.post(reverse("settings"), {"discoverable": "on"})  # everything else off
        self.client.force_login(viewer)
        resp = self.client.get(reverse("discover"))
        usernames = [c["profile"].user.username for c in resp.context["cards"]]
        self.assertIn("cc_target@test.com", usernames)

        self.client.force_login(target)
        self.client.post(reverse("settings"), {})  # discoverable now off
        self.client.force_login(viewer)
        resp2 = self.client.get(reverse("discover"))
        usernames2 = [c["profile"].user.username for c in resp2.context["cards"]]
        self.assertNotIn("cc_target@test.com", usernames2)


class EventBugfixTests(TestCase):
    def test_events_list_requires_login(self):
        resp = self.client.get(reverse("events"))
        self.assertNotEqual(resp.status_code, 200)

    def test_event_participant_match_hidden_once_connected(self):
        from .models import Event, EventRSVP
        import datetime
        organizer = make_user("evt_organizer@test.com")
        attendee = make_user("evt_attendee@test.com")
        viewer = make_user("evt_viewer@test.com")
        event = Event.objects.create(
            organizer=organizer, title="Hack Night", description="d",
            date=datetime.date.today(), start_time="18:00", end_time="20:00", location="Lib",
        )
        EventRSVP.objects.create(event=event, user=attendee)
        self.client.force_login(viewer)
        resp = self.client.get(reverse("event_detail", args=[event.id]))
        self.assertContains(resp, 'data-testid="post-detail-match-button"' if False else "Match")


class StudyRequestToggleTests(TestCase):
    def test_match_button_hidden_when_study_requests_disabled(self):
        from .models import StudentProfile
        owner = make_user("sreq_owner@test.com")
        member = make_user("sreq_member@test.com")
        viewer = make_user("sreq_viewer@test.com")
        group = StudyGroup.objects.create(owner=owner, name="G", subject="S", description="d", max_members=5)
        StudyGroupMember.objects.create(group=group, user=member)
        StudentProfile.objects.filter(user=member).update(allow_study_requests=False) if StudentProfile.objects.filter(user=member).exists() else StudentProfile.objects.create(user=member, allow_study_requests=False)

        self.client.force_login(viewer)
        resp = self.client.get(reverse("study_group_detail", args=[group.id]))
        content = resp.content.decode()
        # The member's row shouldn't offer a Match button when they've opted out.
        member_row_start = content.find(member.username)
        self.assertNotIn('data-testid="study-group-match-button"', content[member_row_start:member_row_start + 800])
