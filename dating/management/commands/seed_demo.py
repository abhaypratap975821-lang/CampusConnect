from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from dating.models import College, ConnectionRequest, Event, Interest, Match, Post, StudentProfile, StudyGroup, StudyGroupMember


class Command(BaseCommand):
    help = "Create realistic local CampusConnect demo data"

    def handle(self, *args, **options):
        college_names = [
            ("Northstar Institute", "Pune"),
            ("Lakeside University", "Bengaluru"),
            ("Harbor School of Design", "Mumbai"),
            ("Cedar Tech College", "Delhi"),
            ("Westbridge Arts", "Hyderabad"),
        ]
        colleges = [College.objects.get_or_create(name=name, city=city)[0] for name, city in college_names]
        names = ["Aarav", "Maya", "Ishaan", "Riya", "Kabir", "Ananya", "Dev", "Zoya", "Vihaan", "Meera",
                 "Arjun", "Naina", "Reyansh", "Tara", "Neil", "Sana", "Aditya", "Kiara", "Rohan", "Ira"]
        interest_names = ["Coding", "Music", "Movies", "Gaming", "Sports", "Photography", "Travel", "Reading",
                           "Fitness", "Art", "Entrepreneurship", "Technology", "Design", "Coffee", "Volunteering"]
        interests = [Interest.objects.get_or_create(name=name, slug=slugify(name))[0] for name in interest_names]

        users = []
        for index, name in enumerate(names):
            email = f"{name.lower()}{index + 1}@campusconnect.demo"
            user, created = User.objects.get_or_create(username=email, defaults={"first_name": name, "last_name": "Student", "email": email})
            if created:
                user.set_password("CampusDemo123!")
                user.save()
            profile, _ = StudentProfile.objects.get_or_create(user=user, defaults={
                "college": colleges[index % 5],
                "course": ["Computer Science", "Psychology", "Product Design", "Data Science"][index % 4],
                "department": "School of Learning",
                "year": (index % 4) + 1,
                "city": colleges[index % 5].city,
                "bio": [
                    "Building useful things and collecting good conversations.",
                    "Always up for a study sprint or a sunset walk.",
                    "Curious about people, products, and this campus.",
                ][index % 3],
                "hobbies": "music, coffee, weekend plans",
                "academic_interests": "technology, design, research",
                "personality_tags": "curious, warm, ambitious",
                "looking_for": ["friendship", "study"],
                "dob": date(2004, 1, 1) + timedelta(days=index * 37),
            })
            profile.interests.set(interests[index % 8:(index % 8) + 4])
            users.append(user)

        for index, user in enumerate(users[:10]):
            Post.objects.get_or_create(author=user, content=[
                "The library has the best quiet corners after 6 PM.",
                "Anyone going to the design workshop this Friday?",
                "Small win: shipped my first campus project today.",
                "Looking for a Python study partner before midterms.",
            ][index % 4])

        for index, title in enumerate(["Northstar Hack Night", "Campus Film Circle", "Design Futures Workshop", "Inter-college Sports Meet", "Open Mic Under The Stars"]):
            Event.objects.get_or_create(organizer=users[index], title=title, defaults={
                "college": colleges[index],
                "description": "Meet students from across campus for a thoughtful, low-pressure evening.",
                "category": ["hackathon", "movie-night", "workshop", "sports", "cultural"][index],
                "date": date.today() + timedelta(days=index + 3),
                "start_time": "18:00",
                "location": "Student Commons",
                "max_attendees": 120,
            })

        for index, title in enumerate(["SQL Sprint", "Machine Learning Lab", "Design critique crew", "Statistics before exams", "Frontend builders"]):
            group, _ = StudyGroup.objects.get_or_create(owner=users[index], name=title, defaults={
                "subject": "Computer Science",
                "description": "Friendly weekly sessions with clear goals and shared notes.",
                "max_members": 8,
                "study_goal": "Learn together, leave with progress",
                "schedule": "Tuesday + Thursday, 7 PM",
            })
            StudyGroupMember.objects.get_or_create(group=group, user=users[index])

        for index in range(0, 8, 2):
            ConnectionRequest.objects.get_or_create(sender=users[index], receiver=users[index + 1], defaults={"status": "accepted"})
            ConnectionRequest.objects.get_or_create(sender=users[index + 1], receiver=users[index], defaults={"status": "accepted"})
            a, b = sorted([users[index].id, users[index + 1].id])
            Match.objects.get_or_create(user_a_id=a, user_b_id=b)

        self.stdout.write(self.style.SUCCESS("Seeded 20 students, 5 colleges, 15 interests, matches, posts, events, and study groups."))
        self.stdout.write(self.style.SUCCESS("Demo login: any <name>@campusconnect.demo (e.g. aarav1@campusconnect.demo) / password CampusDemo123!"))
