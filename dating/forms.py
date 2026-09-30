from datetime import date

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone

from .models import College, Event, Interest, Post, StudentProfile


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=80)
    last_name = forms.CharField(max_length=80)
    email = forms.EmailField()
    college = forms.ModelChoiceField(queryset=College.objects.all())
    course = forms.CharField(max_length=120)
    dob = forms.DateField(required=True, widget=forms.DateInput(attrs={"type": "date"}))
    terms = forms.BooleanField(label="I agree to the CampusConnect terms")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("That email is already connected to a CampusConnect account.")
        return email

    def clean_dob(self):
        dob = self.cleaned_data.get("dob")
        if not dob:
            return dob

        today = timezone.localdate()
        try:
            cutoff = date(today.year - 18, today.month, today.day)
        except ValueError:
            cutoff = date(today.year - 18, 2, 28)

        if dob > cutoff:
            raise forms.ValidationError("You must be 18 or older to join CampusConnect.")
        if dob > today:
            raise forms.ValidationError("Date of birth cannot be in the future.")
        return dob

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = self.cleaned_data["email"].lower()
        user.email = self.cleaned_data["email"].lower()
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            StudentProfile.objects.create(
                user=user,
                college=self.cleaned_data["college"],
                course=self.cleaned_data["course"],
                dob=self.cleaned_data.get("dob"),
            )
        return user


class ProfileForm(forms.ModelForm):
    interests = forms.ModelMultipleChoiceField(queryset=Interest.objects.all(), required=False, widget=forms.CheckboxSelectMultiple)
    looking_for = forms.MultipleChoiceField(choices=StudentProfile.LOOKING_FOR, required=False, widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = StudentProfile
        fields = [
            "college", "dob", "course", "department", "year", "city", "bio",
            "hobbies", "academic_interests", "personality_tags", "looking_for",
            "interests", "discoverable", "show_age", "show_college", "show_online",
            "allow_study_requests",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
            "hobbies": forms.TextInput(attrs={"placeholder": "e.g. badminton, playlists, late-night chai"}),
            "academic_interests": forms.TextInput(attrs={"placeholder": "e.g. product design, robotics, psychology"}),
            "personality_tags": forms.TextInput(attrs={"placeholder": "e.g. curious, calm, builder"}),
        }


class PhotoForm(forms.Form):
    image = forms.ImageField()


class PostForm(forms.ModelForm):
    class Meta:
        model = Post
        fields = ["content", "image"]
        widgets = {"content": forms.Textarea(attrs={"rows": 3, "placeholder": "Share something happening on campus..."})}


class CommentForm(forms.Form):
    body = forms.CharField(max_length=500, widget=forms.TextInput(attrs={"placeholder": "Add a thoughtful reply..."}))


class EventForm(forms.ModelForm):
    max_attendees = forms.IntegerField(min_value=1, max_value=10000, initial=100)

    class Meta:
        model = Event
        fields = ["title", "description", "category", "college", "date", "start_time", "end_time", "location", "max_attendees", "image"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "category": forms.Select(attrs={"class": "cc-dark-select"}),
            "college": forms.Select(attrs={"class": "cc-dark-select"}),
        }


class StudyGroupForm(forms.Form):
    name = forms.CharField(max_length=120)
    subject = forms.CharField(max_length=120)
    description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    topics = forms.CharField(max_length=300, required=False, help_text="Comma-separated, e.g. Django, REST API, Deployment")
    max_members = forms.IntegerField(min_value=2, max_value=50, initial=8)
    study_goal = forms.CharField(max_length=240, required=False)
    schedule = forms.CharField(max_length=160, required=False, help_text="e.g. Tue + Thu, 7 PM")


class ReportForm(forms.ModelForm):
    class Meta:
        from .models import Report
        model = Report
        fields = ["object_type", "reason", "details"]
        widgets = {"details": forms.Textarea(attrs={"rows": 4, "placeholder": "Add any details that will help us review this."})}
