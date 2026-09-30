# CampusConnect

A campus social/networking app for college students — discover people, match,
message in real time, join study groups, find events, and post to a campus feed.

This project was reassembled and completed from a partially broken export
(duplicated/garbled config files, an app referenced by the wrong name, and
~15 empty template files). Everything below now runs end to end; the visual
theme (colors, layout, typography in `static/css/main.css`) was kept exactly
as provided.

## Features
- Email-based registration/login with a student profile (college, course, bio, interests, photos)
- **Campus Cards** discovery feed with connect / save / skip / block actions and a compatibility score
- **Connections** inbox for incoming/outgoing requests and saved profiles
- **Matches** once a connection is accepted, plus unmatching
- **Messages** with a real-time chat screen (Django Channels + WebSockets, with a fallback to a normal form POST)
- **StudyMatch** — create and join study groups
- **Campus Events** — host events and RSVP
- **Campus Feed** — post, like, comment
- **Notifications** for connections, matches, likes, and comments
- **Privacy settings** and a **Safety** page with blocking + reporting
- Demo data seed command

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py seed_demo       # optional: creates 20 demo students, colleges, events, etc.
python manage.py createsuperuser # optional: for /admin/

python manage.py runserver
```

Visit http://127.0.0.1:8000/

Demo accounts (after `seed_demo`): any `<name>@campusconnect.demo`
(e.g. `aarav1@campusconnect.demo`), password `CampusDemo123!`.

### Real-time chat
Chat works over WebSockets via Django Channels, using the in-memory channel
layer configured in `settings.py`. `runserver` (via `daphne`, already listed
in `INSTALLED_APPS`) serves both HTTP and WebSocket traffic, so no extra
setup is required for local development. For production, swap the channel
layer for Redis and run behind an ASGI server (`daphne` or `uvicorn`) using
`campusconnect.asgi:application`.

## Project layout

```
campusconnect/        Django project settings, URLs, ASGI/WSGI entrypoints
dating/                The app: models, views, forms, consumers (chat), admin
templates/             All HTML templates (base theme + one per page)
static/css, static/js  The CampusConnect visual theme (unchanged)
```


## Match Flow (Updated)

- Match requests are created as `pending` and appear only in **Recent Match Requests** on the Matches page.
- Accepting creates the `Match`, creates its private 1-to-1 `Conversation`, adds both members, and moves the person into **Active Matches** without a page reload when using the AJAX UI.
- Rejecting removes the request from the pending UI without creating a Match.
- Unmatching removes the active Match and private conversation, marks the previous request reusable, and allows the next Match click to start a fresh pending request.
- Direct profile-to-profile messaging is disabled until a Match exists.
- Campus Feed and Campus Cards Match actions use AJAX so the target profile is not opened just to send a request.
- Mobile navigation now includes Matches, and match/dashboard panels include responsive touch-friendly layouts.


## Run on Windows (PowerShell)

From the folder that contains `manage.py`:

```powershell
C:\Users\abhay\AppData\Local\Programs\Python\Python312\python.exe manage.py check
C:\Users\abhay\AppData\Local\Programs\Python\Python312\python.exe manage.py runserver
```

Then open `http://127.0.0.1:8000/`.

## Match lifecycle

`Match` click → `pending` request → receiver Accept/Reject → Accept creates the active Match and private conversation → Unmatch removes the active Match and private conversation and makes the pair eligible for a new pending request.


### Render / production start command

For Render, `RENDER_EXTERNAL_HOSTNAME` is used automatically to allow the service hostname and trust its HTTPS origin. Set `DJANGO_SECRET_KEY` in the Render environment and set `DEBUG=False` explicitly for production.

This project uses Django Channels for chat and StudyMatch video-call signaling, so use the ASGI application in production:

```bash
python manage.py collectstatic --noinput
daphne -b 0.0.0.0 -p $PORT campusconnect.asgi:application
```

The repository also includes a `Procfile` with the same command.

### Anime backgrounds

Each major page now gets its own full-page anime artwork from `static/anime/`. The previous top-of-page anime banner has been removed.
