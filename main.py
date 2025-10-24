from __future__ import annotations

from dataclasses import dataclass
from typing import List

from flask import Flask, jsonify, redirect, render_template, request, url_for


app = Flask(__name__)

# Allow routes to respond to both `/path` and `/path/` so that users who
# bookmark a trailing slash variant do not receive a 404 that might look like
# a timeout when the browser keeps retrying.
app.url_map.strict_slashes = False


@dataclass
class CostumeSignup:
    name: str
    costume: str
    contact: str


@dataclass
class KaraokeSignup:
    name: str
    song_title: str
    artist: str


# In-memory stores for signups. In a production application this would be persisted.
costume_signups: List[CostumeSignup] = []
karaoke_signups: List[KaraokeSignup] = []

# Demo slides to rotate on the home page
SLIDES = [
    {
        "title": "Tonight's Lineup",
        "content": "Costume contest judging kicks off at 9:30 PM followed by karaoke at 10:15 PM. Make sure you're signed up!",
    },
    {
        "title": "Welcome to the Halloween Bash!",
        "content": "Check out the event schedule and make sure to submit your signups.",
    },
    {
        "title": "Costume Contest Highlights",
        "content": "Show off your creativity! Sign up to compete for spooky bragging rights.",
    },
    {
        "title": "Karaoke Night",
        "content": "Pick your favorite song and take center stage on karaoke night.",
    },
]


def build_rotation_entries() -> List[dict[str, object]]:
    rotation_entries: List[dict[str, object]] = [
        {
            "category": "Signup Portal",
            "primary": "Get guests connected and ready to register.",
            "secondary": "Share the Wi-Fi credentials and direct them to the Halloween signup page.",
            "cta": True,
            "link": "http://10.0.0.241/halloween",
            "link_label": "Open the signup portal",
            "cta_details": {
                "lede": "Sign Up Instructions!",
                "wifi_network": "Halloween Party Wi-Fi",
                "wifi_password": "halloween",
                "portal_url": "http://10.0.0.241/halloween",
                "portal_label": "http://10.0.0.241/halloween",
                "portal_note": "Type the address exactly as shown and add a bookmark for quick access later.",
                "reminder": "",
            },
        },
        {
            "category": "Event Spotlight",
            "primary": "Tonight's Lineup",
            "secondary": "Costume contest judging kicks off at 9:30 PM followed by karaoke at 11:00 PM. Make sure you're signed up!",
        },
        {
            "category": "Event Spotlight",
            "primary": "Welcome to the Halloween Bash!",
            "secondary": "Check out the event schedule and make sure to submit your signups.",
        },
        {
            "category": "Event Spotlight",
            "primary": "Costume Contest",
            "secondary": "Summon your most sinister look—compete for spine-tingling glory, devilish loot, and the Trophy of Terror.",
        },
        {
            "category": "Event Spotlight",
            "primary": "Karaoke Night",
            "secondary": "Choose your eerie anthem and send shivers down the spine.",
        },
    ]

    costume_entries = [
        {
            "category": "Costume Contest",
            "primary": signup.name,
            "secondary": f"Dressed as {signup.costume}",
            "tertiary": f"Contact: {signup.contact}" if signup.contact else "",
        }
        for signup in costume_signups
    ]

    karaoke_entries = [
        {
            "category": "Karaoke Stage",
            "primary": signup.name,
            "secondary": f'Performing "{signup.song_title}"',
            "tertiary": f"by {signup.artist}" if signup.artist else "",
        }
        for signup in karaoke_signups
    ]

    max_length = max(len(costume_entries), len(karaoke_entries))
    for index in range(max_length):
        if index < len(costume_entries):
            rotation_entries.append(costume_entries[index])
        if index < len(karaoke_entries):
            rotation_entries.append(karaoke_entries[index])

    return rotation_entries


@app.route("/")
def index():
    return redirect(url_for("live_display"))


@app.route("/live-display")
def live_display():
    rotation_entries = build_rotation_entries()

    return render_template(
        "display.html",
        entries=rotation_entries,
        costume_count=len(costume_signups),
        karaoke_count=len(karaoke_signups),
    )


@app.route("/api/display-data")
def display_data():
    rotation_entries = build_rotation_entries()

    return jsonify(
        {
            "entries": rotation_entries,
            "costume_count": len(costume_signups),
            "karaoke_count": len(karaoke_signups),
        }
    )


@app.route("/halloween")
def halloween_overview():
    return render_template(
        "index.html",
        slides=SLIDES,
        costume_signups=costume_signups,
        karaoke_signups=karaoke_signups,
    )


@app.route("/admin", methods=["GET", "POST"])
def admin_portal():
    errors: List[str] = []
    messages: List[str] = []

    def parse_index(raw_index: str | None, total: int, label: str) -> int | None:
        if raw_index is None:
            errors.append(f"Missing {label} index.")
            return None
        try:
            index_value = int(raw_index)
        except ValueError:
            errors.append(f"Invalid {label} index.")
            return None
        if not 0 <= index_value < total:
            errors.append(f"{label.capitalize()} entry could not be found.")
            return None
        return index_value

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "update_costume":
            index = parse_index(request.form.get("index"), len(costume_signups), "costume signup")
            name = request.form.get("name", "").strip()
            costume = request.form.get("costume", "").strip()
            contact = request.form.get("contact", "").strip()

            if not name:
                errors.append("Costume signup name is required.")
            if not costume:
                errors.append("Costume description is required.")

            if index is not None and name and costume:
                costume_signups[index] = CostumeSignup(name=name, costume=costume, contact=contact)
                messages.append(f"Updated costume signup for {name}.")

        elif action == "delete_costume":
            index = parse_index(request.form.get("index"), len(costume_signups), "costume signup")
            if index is not None:
                removed = costume_signups.pop(index)
                messages.append(f"Removed costume signup for {removed.name}.")

        elif action == "add_costume":
            name = request.form.get("name", "").strip()
            costume = request.form.get("costume", "").strip()
            contact = request.form.get("contact", "").strip()

            if not name:
                errors.append("Costume signup name is required to add a new entry.")
            if not costume:
                errors.append("Costume description is required to add a new entry.")

            if name and costume:
                costume_signups.append(CostumeSignup(name=name, costume=costume, contact=contact))
                messages.append(f"Added costume signup for {name}.")

        elif action == "update_karaoke":
            index = parse_index(request.form.get("index"), len(karaoke_signups), "karaoke signup")
            name = request.form.get("name", "").strip()
            song_title = request.form.get("song_title", "").strip()
            artist = request.form.get("artist", "").strip()

            if not name:
                errors.append("Karaoke signup name is required.")
            if not song_title:
                errors.append("Song title is required.")

            if index is not None and name and song_title:
                karaoke_signups[index] = KaraokeSignup(name=name, song_title=song_title, artist=artist)
                messages.append(f"Updated karaoke signup for {name}.")

        elif action == "delete_karaoke":
            index = parse_index(request.form.get("index"), len(karaoke_signups), "karaoke signup")
            if index is not None:
                removed = karaoke_signups.pop(index)
                messages.append(f"Removed karaoke signup for {removed.name}.")

        elif action == "add_karaoke":
            name = request.form.get("name", "").strip()
            song_title = request.form.get("song_title", "").strip()
            artist = request.form.get("artist", "").strip()

            if not name:
                errors.append("Karaoke signup name is required to add a new entry.")
            if not song_title:
                errors.append("Song title is required to add a new entry.")

            if name and song_title:
                karaoke_signups.append(KaraokeSignup(name=name, song_title=song_title, artist=artist))
                messages.append(f"Added karaoke signup for {name}.")

        else:
            errors.append("Unknown action submitted. Please try again.")

    return render_template(
        "admin.html",
        costume_signups=costume_signups,
        karaoke_signups=karaoke_signups,
        errors=errors,
        messages=messages,
    )


@app.route("/costume-signup", methods=["GET", "POST"])
def costume_signup():
    errors: List[str] = []
    submitted = False

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        costume = request.form.get("costume", "").strip()
        contact = request.form.get("contact", "").strip()

        if not name:
            errors.append("Name is required.")
        if not costume:
            errors.append("Costume description is required.")

        if not errors:
            costume_signups.append(CostumeSignup(name=name, costume=costume, contact=contact))
            submitted = True
            return redirect(url_for("costume_signup", success="1"))

    if request.args.get("success") == "1":
        submitted = True

    return render_template(
        "costume_signup.html",
        errors=errors,
        submitted=submitted,
        costume_signups=costume_signups,
    )


@app.route("/karaoke-signup", methods=["GET", "POST"])
def karaoke_signup():
    errors: List[str] = []
    submitted = False

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        song_title = request.form.get("song_title", "").strip()
        artist = request.form.get("artist", "").strip()

        if not name:
            errors.append("Name is required.")
        if not song_title:
            errors.append("Song title is required.")

        if not errors:
            karaoke_signups.append(
                KaraokeSignup(name=name, song_title=song_title, artist=artist)
            )
            submitted = True
            return redirect(url_for("karaoke_signup", success="1"))

    if request.args.get("success") == "1":
        submitted = True

    return render_template(
        "karaoke_signup.html",
        errors=errors,
        submitted=submitted,
        karaoke_signups=karaoke_signups,
    )


if __name__ == "__main__":
    # Run on port 80 so the app is available from any browser.
    app.run(host="0.0.0.0", port=80, debug=True)
