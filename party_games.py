from __future__ import annotations

import copy
import hashlib
import random
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4


TWO_TRUTHS_GAME_KEY = "two_truths_and_a_lie"
MURDER_MARRY_FUCK_GAME_KEY = "murder_marry_fuck"
FILL_BLANK_GAME_KEY = "fill_in_the_blank"
BAD_ADVICE_GAME_KEY = "bad_advice_hotline"
WRONG_ANSWERS_GAME_KEY = "wrong_answers_only"
CURSED_OBJECTIVES_GAME_KEY = "cursed_objectives"
PROMPT_GAME_KEYS = (FILL_BLANK_GAME_KEY, BAD_ADVICE_GAME_KEY, WRONG_ANSWERS_GAME_KEY)
GAME_PHASES = {"signup", "active", "ended"}
PROMPT_ROUND_PHASES = {"submissions", "voting", "revealed"}
PROMPT_RESPONSE_MINIMUM = 3
PROMPT_RESPONSE_WINDOW_SECONDS = 10 * 60
PROMPT_VOTING_WINDOW_SECONDS = 5 * 60
PROMPT_REVEAL_WINDOW_SECONDS = 30
PROMPT_RECENT_FINGERPRINT_LIMIT = 50
PROMPT_GENERATOR_VERSION = 1
GAME_STATEMENT_MAX_LENGTH = 240
GAME_PROMPT_MAX_LENGTH = 240
GAME_RESPONSE_MAX_LENGTH = 280
MMF_ROUND_COUNT = 10
MMF_ACTIONS = ("murder", "marry", "fuck")
CURSED_OBJECTIVES_PER_PLAYER = 3


GAME_CATALOG: dict[str, dict[str, str]] = {
    TWO_TRUTHS_GAME_KEY: {
        "slug": "two-truths-and-a-lie",
        "title": "Two Truths and a Lie",
        "short_title": "Two Truths",
        "engine": "identity",
        "description": "Submit two truths and a lie, then identify the mystery guests.",
        "image": "images/games/two-truths-and-a-lie.jpg",
        "winner_image": "images/games/winners/two-truths-and-a-lie-winner.jpg",
        "personality": "Three stories enter the lab. Only one is fabricated.",
        "solo_note": "Opens immediately; guessing grows as guests join.",
    },
    MURDER_MARRY_FUCK_GAME_KEY: {
        "slug": "murder-marry-fuck",
        "title": "Murder, Marry, F%$@",
        "short_title": "Murder / Marry / F%$@",
        "engine": "choice",
        "description": "Assign three famous adults to three impossible choices across ten rounds.",
        "image": "images/games/murder-marry-fuck.jpg",
        "winner_image": "images/games/winners/murder-marry-fuck-winner.jpg",
        "personality": "Ten infamous trios. Three irreversible decisions.",
        "solo_note": "Solo play supported.",
    },
    FILL_BLANK_GAME_KEY: {
        "slug": "fill-in-the-blank",
        "title": "Fill in the Blank: After Dark",
        "short_title": "Fill in the Blank",
        "engine": "prompt_vote",
        "description": "Complete an edgy prompt and vote for the funniest anonymous answer.",
        "image": "images/games/fill-in-the-blank.jpg",
        "winner_image": "images/games/winners/fill-in-the-blank-winner.jpg",
        "personality": "Complete the sentence. Compromise your dignity.",
        "solo_note": "Solo spotlight supported.",
    },
    BAD_ADVICE_GAME_KEY: {
        "slug": "bad-advice-hotline",
        "title": "Bad Advice Hotline",
        "short_title": "Bad Advice",
        "engine": "prompt_vote",
        "description": "Give the worst possible advice for a completely fictional dilemma.",
        "image": "images/games/bad-advice-hotline.jpg",
        "winner_image": "images/games/winners/bad-advice-hotline-winner.jpg",
        "personality": "The hotline is open. Good judgment is not.",
        "solo_note": "Solo spotlight supported.",
    },
    WRONG_ANSWERS_GAME_KEY: {
        "slug": "wrong-answers-only",
        "title": "Wrong Answers Only",
        "short_title": "Wrong Answers",
        "engine": "prompt_vote",
        "description": "Answer a ridiculous question as incorrectly as possible.",
        "image": "images/games/wrong-answers-only.jpg",
        "winner_image": "images/games/winners/wrong-answers-only-winner.jpg",
        "personality": "Accuracy is suspicious. Confidence earns the applause.",
        "solo_note": "Solo spotlight supported.",
    },
    CURSED_OBJECTIVES_GAME_KEY: {
        "slug": "cursed-objectives",
        "title": "Cursed Objectives",
        "short_title": "Cursed Objectives",
        "engine": "secret_missions",
        "description": "Complete three private social missions before the hosts close the game.",
        "image": "images/games/cursed-objectives.jpg",
        "winner_image": "images/games/winners/cursed-objectives-winner.jpg",
        "personality": "Three secret objectives. One night to finish the ritual.",
        "solo_note": "Every player receives a different, private mission set.",
    },
}

GAME_KEY_BY_SLUG = {entry["slug"]: key for key, entry in GAME_CATALOG.items()}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_guess_name(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def normalize_statement(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:GAME_STATEMENT_MAX_LENGTH]


def normalize_prompt(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:GAME_PROMPT_MAX_LENGTH]


def normalize_response(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:GAME_RESPONSE_MAX_LENGTH]


def normalize_player_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())[:80]


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _phase(value: object, default: str = "signup") -> str:
    phase = str(value or default)
    return phase if phase in GAME_PHASES else default


def _presentation(raw: object) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "active": bool(source.get("active")),
        "slide_index": _nonnegative_int(source.get("slide_index")),
    }


def _simulation(raw: object) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "is_simulated": bool(source.get("is_simulated")),
        "player_count": _nonnegative_int(source.get("player_count")),
        "generated_at": str(source.get("generated_at", "") or ""),
    }


DEFAULT_TWO_TRUTHS_GAME_STATE: dict[str, Any] = {
    "enabled": False,
    "phase": "signup",
    "started_at": "",
    "ended_at": "",
    "participants": {},
    "guesses": {},
    "results": {
        "finalized_at": "",
        "scores": [],
        "winner_ids": [],
        "participant_results": [],
    },
    "simulation": {"is_simulated": False, "player_count": 0, "generated_at": ""},
}


DEFAULT_MMF_ROUNDS: list[dict[str, Any]] = [
    {"id": "mmf-01", "people": [{"id": "martha-stewart", "name": "Martha Stewart", "image_url": ""}, {"id": "snoop-dogg", "name": "Snoop Dogg", "image_url": ""}, {"id": "gordon-ramsay", "name": "Gordon Ramsay", "image_url": ""}]},
    {"id": "mmf-02", "people": [{"id": "dolly-parton", "name": "Dolly Parton", "image_url": ""}, {"id": "pedro-pascal", "name": "Pedro Pascal", "image_url": ""}, {"id": "keanu-reeves", "name": "Keanu Reeves", "image_url": ""}]},
    {"id": "mmf-03", "people": [{"id": "lady-gaga", "name": "Lady Gaga", "image_url": ""}, {"id": "jason-momoa", "name": "Jason Momoa", "image_url": ""}, {"id": "rihanna", "name": "Rihanna", "image_url": ""}]},
    {"id": "mmf-04", "people": [{"id": "danny-devito", "name": "Danny DeVito", "image_url": ""}, {"id": "jeff-goldblum", "name": "Jeff Goldblum", "image_url": ""}, {"id": "stanley-tucci", "name": "Stanley Tucci", "image_url": ""}]},
    {"id": "mmf-05", "people": [{"id": "beyonce", "name": "Beyonce", "image_url": ""}, {"id": "megan-thee-stallion", "name": "Megan Thee Stallion", "image_url": ""}, {"id": "cardi-b", "name": "Cardi B", "image_url": ""}]},
    {"id": "mmf-06", "people": [{"id": "ryan-reynolds", "name": "Ryan Reynolds", "image_url": ""}, {"id": "idris-elba", "name": "Idris Elba", "image_url": ""}, {"id": "oscar-isaac", "name": "Oscar Isaac", "image_url": ""}]},
    {"id": "mmf-07", "people": [{"id": "cher", "name": "Cher", "image_url": ""}, {"id": "madonna", "name": "Madonna", "image_url": ""}, {"id": "jennifer-coolidge", "name": "Jennifer Coolidge", "image_url": ""}]},
    {"id": "mmf-08", "people": [{"id": "nicolas-cage", "name": "Nicolas Cage", "image_url": ""}, {"id": "willem-dafoe", "name": "Willem Dafoe", "image_url": ""}, {"id": "steve-buscemi", "name": "Steve Buscemi", "image_url": ""}]},
    {"id": "mmf-09", "people": [{"id": "britney-spears", "name": "Britney Spears", "image_url": ""}, {"id": "christina-aguilera", "name": "Christina Aguilera", "image_url": ""}, {"id": "pink", "name": "Pink", "image_url": ""}]},
    {"id": "mmf-10", "people": [{"id": "dwayne-johnson", "name": "Dwayne Johnson", "image_url": ""}, {"id": "john-cena", "name": "John Cena", "image_url": ""}, {"id": "dave-bautista", "name": "Dave Bautista", "image_url": ""}]},
]


DEFAULT_PROMPTS: dict[str, list[str]] = {
    FILL_BLANK_GAME_KEY: [
        "Nothing ruins the mood faster than ___.",
        "The real reason I was late was ___.",
        "The least sexy thing to whisper is ___.",
        "Tonight's safe word is ___.",
        "My dating profile only says ___.",
    ],
    BAD_ADVICE_GAME_KEY: [
        "My ex texted 'you awake?' at 2 AM. What should I do?",
        "I accidentally sent the group chat screenshot to the group chat. Help.",
        "My date brought their parents. How do I salvage the evening?",
        "I lied on my resume and start tomorrow. Any tips?",
        "The hotel says the handcuffs are not complimentary. What now?",
    ],
    WRONG_ANSWERS_GAME_KEY: [
        "What is the worst possible safe word?",
        "What does HR actually stand for?",
        "What should never be served at a wedding?",
        "Why did the neighbors call the police?",
        "What is the secret ingredient in a lasting relationship?",
    ],
}


DEFAULT_CURSED_OBJECTIVES: list[str] = [
    "Get someone to say, ‘That is definitely haunted.’",
    "Convince someone to recommend a karaoke song for you.",
    "Get two people to disagree about the best Halloween candy.",
    "Make someone laugh using only a dramatic facial expression.",
    "Get someone to tell you the story behind their costume.",
    "Start a three-person toast to something ridiculous.",
    "Get someone to use the word ‘ominous’ in conversation.",
    "Find someone who has watched a horror movie this week.",
    "Get someone to show you their best villain pose.",
    "Persuade someone that a harmless decoration has a secret name.",
    "Get two people to rank vampire, werewolf, and ghost.",
    "Find someone whose costume includes something handmade.",
    "Get someone to hum a spooky song without naming it.",
    "Make someone say, ‘I would survive a horror movie.’",
    "Get someone to invent a title for an imaginary horror sequel.",
    "Find two people wearing the same color and introduce them.",
    "Get someone to name a fictional monster they could defeat.",
    "Convince someone to describe the party in exactly three words.",
    "Get someone to demonstrate their emergency dance move.",
    "Find someone who can name three actors from horror movies.",
    "Get someone to say which room they would never enter in a haunted house.",
    "Make someone choose between a cursed mirror and a haunted doll.",
    "Get two people to create a secret handshake with you.",
    "Find someone who has worn more than one costume this Halloween season.",
    "Get someone to give a one-sentence ghost story.",
    "Make someone say, ‘That sounds like a terrible idea.’",
    "Get someone to name the worst possible superpower.",
    "Find someone who would volunteer to investigate a strange noise.",
    "Get someone to rate their own costume entrance from one to ten.",
    "Persuade someone to give an ordinary object a sinister backstory.",
    "Get someone to name their ideal monster-fighting sidekick.",
    "Find someone who prefers practical effects to computer effects.",
    "Get someone to act out being startled by an invisible ghost.",
    "Make someone choose a theme song for their costume.",
    "Get two people to agree on the most suspicious party snack.",
    "Find someone who knows a Halloween joke and get them to tell it.",
    "Get someone to describe their costume as if it were a luxury product.",
    "Make someone say, ‘We should not open that.’",
    "Get someone to invent a warning label for the fog machine.",
    "Find someone who has carved a pumpkin this year.",
    "Get someone to name a song that would wake the dead.",
    "Convince someone to narrate ten seconds of the party like a nature documentary.",
    "Get someone to choose which guest would make the best detective.",
    "Find someone with a costume prop and learn what it does.",
    "Get someone to pitch a haunted-house attraction in one sentence.",
    "Make someone say, ‘I have questions.’",
    "Get two people to pose for an imaginary album cover.",
    "Find someone who can name a classic movie monster.",
    "Get someone to invent a cocktail name inspired by the party.",
    "Make someone choose whether to explore a crypt or an abandoned carnival.",
    "Get someone to demonstrate a silent movie scream.",
    "Find someone wearing an accessory they almost left at home.",
    "Get someone to name the least useful item in a zombie apocalypse.",
    "Convince someone to announce an imaginary plot twist.",
    "Get someone to describe the DJ as a supernatural creature.",
    "Find someone who would spend a night in a reportedly haunted hotel.",
    "Get someone to invent a spell using three party-related words.",
    "Make someone say, ‘This is how the curse starts.’",
    "Get two people to choose a mascot for the party.",
    "Find someone who can do an evil laugh and ask for a demonstration.",
]


PROMPT_GENERATOR_PARTS: dict[str, dict[str, list[str]]] = {
    FILL_BLANK_GAME_KEY: {
        "templates": [
            "The haunted house has one rule: never ___ after {event}.",
            "My villain origin story started when someone ___ near {place}.",
            "The fastest way to get banned from {place} is ___.",
            "This party was perfectly normal until ___ appeared in {place}.",
            "My last text before the group chat went silent was ___.",
            "The warning label on {object} should really say ___.",
        ],
        "event": ["midnight", "last call", "the séance", "karaoke", "the costume contest", "dessert"],
        "place": ["the kitchen", "the dance floor", "the graveyard", "the hotel lobby", "the laboratory", "the group chat"],
        "object": ["the cursed punch bowl", "the fog machine", "the mystery key", "the karaoke microphone", "the velvet cape", "the emergency glitter"],
    },
    BAD_ADVICE_GAME_KEY: {
        "templates": [
            "I accidentally {mistake} right before {event}. What is the worst advice you can give me?",
            "My roommate insists {problem}. How should I make this dramatically worse?",
            "I found {object} in {place}. What is the least responsible next step?",
            "I promised I could {task}, but I absolutely cannot. How do I bluff my way through it?",
            "The host just announced {problem}. What terrible advice should I follow?",
        ],
        "mistake": ["invited both of my exes", "replied all to the family email", "wore the same costume as my nemesis", "lost the only key", "volunteered to make a speech", "called the DJ by the wrong name"],
        "event": ["a first date", "the costume judging", "a wedding toast", "the big presentation", "midnight karaoke", "a very formal dinner"],
        "problem": ["the house is definitely haunted", "everyone must perform a solo", "the punch bowl is judging us", "the neighbors have started a rival party", "the group chat needs a leader", "the fog machine is now sentient"],
        "object": ["a suspicious envelope", "an unlabeled potion", "a tiny velvet throne", "a key marked DO NOT USE", "a phone with one percent battery", "a coupon for one free alibi"],
        "place": ["the coat closet", "the haunted basement", "the rideshare", "the hotel lobby", "the laboratory", "the dance floor"],
        "task": ["perform an exorcism", "DJ for an hour", "deliver a flawless toast", "repair a fog machine", "judge a dance battle", "decode a mysterious voicemail"],
    },
    WRONG_ANSWERS_GAME_KEY: {
        "templates": [
            "Why is {object} hidden in {place}?",
            "What is the real purpose of {object}?",
            "What should you say when someone announces {event}?",
            "What is the first rule of {activity}?",
            "Why did the host ban {object} after midnight?",
            "What does {phrase} actually mean?",
        ],
        "object": ["the emergency glitter", "the cursed punch bowl", "the velvet cape", "the karaoke microphone", "the mystery key", "the fog machine"],
        "place": ["the freezer", "the coat closet", "the graveyard", "the group chat", "the laboratory", "the rideshare"],
        "event": ["last call", "a surprise séance", "mandatory karaoke", "the final costume vote", "a mysterious delivery", "an unscheduled dance battle"],
        "activity": ["haunted-house etiquette", "midnight karaoke", "competitive pumpkin carving", "group-chat diplomacy", "villain networking", "emergency costume repair"],
        "phrase": ["business casual", "plus one", "last call", "read the room", "circle back", "dress to impress"],
    },
}


def prompt_fingerprint(text: object) -> str:
    normalized = normalize_prompt(text).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]


def _format_generated_prompt(parts: dict[str, list[str]], rng: random.Random) -> str:
    template = rng.choice(parts["templates"])
    values = {
        key: rng.choice(options)
        for key, options in parts.items()
        if key != "templates" and options
    }
    return normalize_prompt(template.format(**values))


def generate_prompt_for_game(
    game_key: str,
    game: dict[str, Any],
    *,
    rng: random.Random | None = None,
) -> dict[str, str | int]:
    """Generate a bounded, privacy-safe prompt and avoid recent repetitions."""
    if game_key not in PROMPT_GAME_KEYS:
        raise KeyError(game_key)
    chooser = rng or random.SystemRandom()
    automation = game.setdefault("automation", {})
    recent = [str(value) for value in automation.get("recent_prompt_fingerprints", []) if value]
    recent_set = set(recent)
    parts = PROMPT_GENERATOR_PARTS[game_key]
    selected = ""
    fingerprint = ""
    for _ in range(100):
        candidate = _format_generated_prompt(parts, chooser)
        candidate_fingerprint = prompt_fingerprint(candidate)
        if candidate and candidate_fingerprint not in recent_set:
            selected = candidate
            fingerprint = candidate_fingerprint
            break
    if not selected:
        enabled_prompts = [
            entry for entry in game.get("prompts", [])
            if isinstance(entry, dict) and entry.get("enabled") and normalize_prompt(entry.get("text"))
        ]
        fallback = chooser.choice(enabled_prompts) if enabled_prompts else {"text": DEFAULT_PROMPTS[game_key][0]}
        selected = normalize_prompt(fallback.get("text"))
        fingerprint = prompt_fingerprint(selected)
    automation["recent_prompt_fingerprints"] = [
        *[value for value in recent if value != fingerprint],
        fingerprint,
    ][-PROMPT_RECENT_FINGERPRINT_LIMIT:]
    return {
        "text": selected,
        "fingerprint": fingerprint,
        "source": "procedural",
        "generator_version": PROMPT_GENERATOR_VERSION,
    }


def default_prompt_records(game_key: str) -> list[dict[str, Any]]:
    return [
        {"id": f"{game_key}-{index + 1:02d}", "text": text, "enabled": True}
        for index, text in enumerate(DEFAULT_PROMPTS.get(game_key, []))
    ]


def empty_two_truths_game_state(*, enabled: bool = False) -> dict[str, Any]:
    state = copy.deepcopy(DEFAULT_TWO_TRUTHS_GAME_STATE)
    state["enabled"] = bool(enabled)
    if enabled:
        state["phase"] = "active"
    return state


def empty_mmf_game_state(*, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "anonymous_mode": False,
        "phase": "active" if enabled else "signup",
        "started_at": "",
        "ended_at": "",
        "explicit_label": "F%$@",
        "rounds": copy.deepcopy(DEFAULT_MMF_ROUNDS),
        "participants": {},
        "results": {"finalized_at": "", "round_results": [], "scores": [], "winner_player_ids": []},
        "presentation": {"active": False, "slide_index": 0},
        "simulation": {"is_simulated": False, "player_count": 0, "generated_at": ""},
    }


def empty_prompt_game_state(game_key: str, *, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "anonymous_mode": False,
        "phase": "active" if enabled else "signup",
        "started_at": "",
        "ended_at": "",
        "participants": {},
        "prompts": default_prompt_records(game_key),
        "rounds": [],
        "current_round_id": "",
        "automation": {
            "enabled": True,
            "paused": False,
            "paused_at": "",
            "remaining_seconds": 0,
            "recent_prompt_fingerprints": [],
            "generator_version": PROMPT_GENERATOR_VERSION,
        },
        "results": {"finalized_at": "", "scores": [], "winner_player_ids": []},
        "presentation": {"active": False, "slide_index": 0},
        "simulation": {"is_simulated": False, "player_count": 0, "generated_at": ""},
    }


def default_cursed_objective_records() -> list[dict[str, Any]]:
    return [
        {"id": f"cursed-objective-{index + 1:02d}", "text": text, "enabled": True}
        for index, text in enumerate(DEFAULT_CURSED_OBJECTIVES)
    ]


def empty_cursed_objectives_game_state(*, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "phase": "active" if enabled else "signup",
        "started_at": "",
        "ended_at": "",
        "objectives": default_cursed_objective_records(),
        "participants": {},
        "results": {"finalized_at": "", "scores": [], "winner_player_ids": []},
        "presentation": {"active": False, "slide_index": 0},
        "simulation": {"is_simulated": False, "player_count": 0, "generated_at": ""},
    }


DEFAULT_GAMES_STATE: dict[str, Any] = {
    TWO_TRUTHS_GAME_KEY: empty_two_truths_game_state(),
    MURDER_MARRY_FUCK_GAME_KEY: empty_mmf_game_state(),
    **{game_key: empty_prompt_game_state(game_key) for game_key in PROMPT_GAME_KEYS},
    CURSED_OBJECTIVES_GAME_KEY: empty_cursed_objectives_game_state(),
}


ALIAS_ADJECTIVES = ("Depraved", "Questionable", "Thirsty", "Chaotic", "Cursed", "Unlicensed", "Suspicious", "Unhinged")
ALIAS_CREATURES = ("Pumpkin", "Vampire", "Poltergeist", "Exorcist", "Goblin", "Werewolf", "Witch", "Skeleton")


def generate_game_alias(existing_aliases: set[str] | None = None) -> str:
    existing = existing_aliases or set()
    options = [f"{adjective} {creature}" for adjective in ALIAS_ADJECTIVES for creature in ALIAS_CREATURES]
    available = [alias for alias in options if alias not in existing]
    if available:
        return secrets.choice(available)
    return f"Mysterious Guest {len(existing) + 1}"


def participant_public_name(
    participant: object,
    fallback: str = "Player",
    *,
    anonymous: bool | None = None,
) -> str:
    if not isinstance(participant, dict):
        return fallback
    alias = normalize_player_name(participant.get("alias")) or fallback
    use_alias = bool(participant.get("anonymous", True)) if anonymous is None else bool(anonymous)
    if use_alias:
        return alias
    return normalize_player_name(participant.get("display_name")) or alias


def normalize_participant(raw: object, user_id: str = "") -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    participant_user_id = str(raw.get("user_id", "") or user_id).strip()
    submission_id = str(raw.get("submission_id", "") or "").strip()
    answer_name = re.sub(r"\s+", " ", str(raw.get("answer_name", "") or "").strip())[:80]
    raw_truths = raw.get("truths", [])
    truths = [normalize_statement(value) for value in raw_truths[:2]] if isinstance(raw_truths, list) else []
    lie = normalize_statement(raw.get("lie", ""))
    if not participant_user_id or not submission_id or not answer_name or len(truths) != 2 or not all(truths) or not lie:
        return None
    normalized_statements = [normalize_guess_name(value) for value in [*truths, lie]]
    if len(set(normalized_statements)) != 3:
        return None
    raw_order = raw.get("display_order", [])
    display_order = []
    if isinstance(raw_order, list):
        for value in raw_order:
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if index in {0, 1, 2} and index not in display_order:
                display_order.append(index)
    if len(display_order) != 3:
        display_order = [0, 1, 2]
    return {
        "submission_id": submission_id,
        "user_id": participant_user_id,
        "answer_name": answer_name,
        "truths": truths,
        "lie": lie,
        "display_order": display_order,
        "created_at": str(raw.get("created_at", "") or ""),
        "updated_at": str(raw.get("updated_at", "") or ""),
    }


def normalize_guess(raw: object) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    guessed_name = re.sub(r"\s+", " ", str(raw.get("guessed_name", "") or "").strip())[:80]
    normalized_name = normalize_guess_name(guessed_name)
    if not guessed_name or not normalized_name:
        return None
    return {"guessed_name": guessed_name, "normalized_name": normalized_name, "submitted_at": str(raw.get("submitted_at", "") or "")}


def normalize_results(raw: object) -> dict[str, Any]:
    default = copy.deepcopy(DEFAULT_TWO_TRUTHS_GAME_STATE["results"])
    if not isinstance(raw, dict):
        return default
    scores = []
    if isinstance(raw.get("scores"), list):
        for entry in raw["scores"]:
            if not isinstance(entry, dict):
                continue
            user_id = str(entry.get("user_id", "") or "")
            name = str(entry.get("name", "") or "").strip()[:80]
            if not user_id or not name:
                continue
            attempts = _nonnegative_int(entry.get("attempts"))
            correct = min(attempts, _nonnegative_int(entry.get("correct")))
            scores.append({"user_id": user_id, "name": name, "correct": correct, "attempts": attempts, "accuracy": round((correct / attempts * 100) if attempts else 0.0, 1)})
    participant_results = []
    if isinstance(raw.get("participant_results"), list):
        for entry in raw["participant_results"]:
            if isinstance(entry, dict):
                participant_results.append({"submission_id": str(entry.get("submission_id", "") or ""), "name": str(entry.get("name", "") or "").strip()[:80], "correct_guesses": _nonnegative_int(entry.get("correct_guesses")), "guess_count": _nonnegative_int(entry.get("guess_count"))})
    valid_user_ids = {entry["user_id"] for entry in scores}
    winner_ids = [str(value) for value in raw.get("winner_ids", []) if str(value) in valid_user_ids] if isinstance(raw.get("winner_ids"), list) else []
    return {"finalized_at": str(raw.get("finalized_at", "") or ""), "scores": scores, "winner_ids": winner_ids, "participant_results": participant_results}


def normalize_two_truths_game_state(raw: object) -> dict[str, Any]:
    state = empty_two_truths_game_state()
    if not isinstance(raw, dict):
        return state
    state["enabled"] = bool(raw.get("enabled"))
    state["phase"] = _phase(raw.get("phase"))
    if state["enabled"] and state["phase"] == "signup":
        state["phase"] = "active"
    state["started_at"] = str(raw.get("started_at", "") or "")
    state["ended_at"] = str(raw.get("ended_at", "") or "")
    participants: dict[str, dict[str, Any]] = {}
    seen_submission_ids: set[str] = set()
    raw_participants = raw.get("participants", {})
    if isinstance(raw_participants, dict):
        for raw_user_id, raw_participant in raw_participants.items():
            participant = normalize_participant(raw_participant, str(raw_user_id))
            if participant and participant["submission_id"] not in seen_submission_ids:
                participants[str(raw_user_id)] = participant
                seen_submission_ids.add(participant["submission_id"])
    state["participants"] = participants
    submission_owners = {entry["submission_id"]: entry["user_id"] for entry in participants.values()}
    guesses: dict[str, dict[str, dict[str, str]]] = {}
    raw_guesses = raw.get("guesses", {})
    if isinstance(raw_guesses, dict):
        for raw_guesser_id, raw_submission_guesses in raw_guesses.items():
            guesser_id = str(raw_guesser_id)
            if guesser_id not in participants or not isinstance(raw_submission_guesses, dict):
                continue
            normalized_submission_guesses = {}
            for raw_submission_id, raw_guess in raw_submission_guesses.items():
                submission_id = str(raw_submission_id)
                guess = normalize_guess(raw_guess)
                if submission_id in submission_owners and submission_owners[submission_id] != guesser_id and guess:
                    normalized_submission_guesses[submission_id] = guess
            if normalized_submission_guesses:
                guesses[guesser_id] = normalized_submission_guesses
    state["guesses"] = guesses
    state["results"] = normalize_results(raw.get("results"))
    state["simulation"] = _simulation(raw.get("simulation"))
    return state


def _slug_id(value: object, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().casefold()).strip("-")
    return (slug or fallback)[:80]


def normalize_mmf_round(raw: object, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    round_id = _slug_id(raw.get("id"), f"mmf-{index + 1:02d}")
    people = []
    seen_ids: set[str] = set()
    raw_people = raw.get("people", [])
    if not isinstance(raw_people, list):
        return None
    for person_index, person in enumerate(raw_people[:3]):
        if not isinstance(person, dict):
            continue
        name = re.sub(r"\s+", " ", str(person.get("name", "") or "").strip())[:80]
        person_id = _slug_id(person.get("id") or name, f"person-{person_index + 1}")
        if not name or person_id in seen_ids:
            continue
        people.append({"id": person_id, "name": name, "image_url": str(person.get("image_url", "") or "").strip()[:500]})
        seen_ids.add(person_id)
    if len(people) != 3:
        return None
    return {"id": round_id, "people": people}


def normalize_alias_participant(raw: object, user_id: str, *, include_answers: bool = False, valid_rounds: dict[str, set[str]] | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    player_id = str(raw.get("player_id", "") or "").strip()[:80]
    alias = normalize_player_name(raw.get("alias"))
    if not user_id or not player_id or not alias:
        return None
    display_name = normalize_player_name(raw.get("display_name"))
    participant = {
        "player_id": player_id,
        "display_name": display_name,
        "alias": alias,
        "created_at": str(raw.get("created_at", "") or ""),
        "updated_at": str(raw.get("updated_at", "") or ""),
    }
    if include_answers:
        answers = {}
        raw_answers = raw.get("answers", {})
        if isinstance(raw_answers, dict):
            for round_id, raw_answer in raw_answers.items():
                if not isinstance(raw_answer, dict) or not valid_rounds or str(round_id) not in valid_rounds:
                    continue
                answer = {action: str(raw_answer.get(action, "") or "") for action in MMF_ACTIONS}
                if set(answer.values()) == valid_rounds[str(round_id)] and len(set(answer.values())) == 3:
                    answers[str(round_id)] = answer
        participant["answers"] = answers
    return participant


def calculate_mmf_results(game: dict[str, Any], *, finalized_at: str | None = None) -> dict[str, Any]:
    participants = game.get("participants", {})
    anonymous_mode = bool(game.get("anonymous_mode"))
    scores_by_player = {str(entry.get("player_id")): 0 for entry in participants.values()}
    identities = {
        str(entry.get("player_id")): {
            "name": participant_public_name(entry, anonymous=anonymous_mode),
            "alias": str(entry.get("alias", "Player")),
            "anonymous": anonymous_mode,
        }
        for entry in participants.values()
    }
    round_results = []
    for game_round in game.get("rounds", []):
        round_id = str(game_round.get("id", ""))
        people = game_round.get("people", [])
        person_ids = {str(person.get("id", "")) for person in people}
        totals = {action: {person_id: 0 for person_id in person_ids} for action in MMF_ACTIONS}
        respondent_count = 0
        for participant in participants.values():
            answer = participant.get("answers", {}).get(round_id, {})
            if set(answer.values()) != person_ids or len(set(answer.values())) != 3:
                continue
            respondent_count += 1
            for action in MMF_ACTIONS:
                totals[action][answer[action]] += 1
        winners: dict[str, list[str]] = {}
        for action in MMF_ACTIONS:
            top = max(totals[action].values(), default=0)
            winners[action] = sorted(person_id for person_id, count in totals[action].items() if top > 0 and count == top)
        for participant in participants.values():
            player_id = str(participant.get("player_id", ""))
            answer = participant.get("answers", {}).get(round_id, {})
            if set(answer.values()) != person_ids or len(set(answer.values())) != 3:
                continue
            scores_by_player[player_id] += sum(1 for action in MMF_ACTIONS if answer.get(action) in winners[action])
        round_results.append({"round_id": round_id, "people": copy.deepcopy(people), "respondent_count": respondent_count, "totals": totals, "winners": winners})
    scores = [
        {
            "player_id": player_id,
            "name": identities.get(player_id, {}).get("name", "Player"),
            "alias": identities.get(player_id, {}).get("alias", "Player"),
            "anonymous": bool(identities.get(player_id, {}).get("anonymous", True)),
            "points": points,
            "completed_rounds": len(next((entry.get("answers", {}) for entry in participants.values() if str(entry.get("player_id")) == player_id), {})),
        }
        for player_id, points in scores_by_player.items()
    ]
    scores.sort(key=lambda entry: (-entry["points"], entry["name"].casefold()))
    top_score = scores[0]["points"] if scores else 0
    winner_player_ids = [entry["player_id"] for entry in scores if top_score > 0 and entry["points"] == top_score]
    return {"finalized_at": finalized_at or utc_now_iso(), "round_results": round_results, "scores": scores, "winner_player_ids": winner_player_ids}


def normalize_mmf_game_state(raw: object) -> dict[str, Any]:
    state = empty_mmf_game_state()
    if not isinstance(raw, dict):
        return state
    state["enabled"] = bool(raw.get("enabled"))
    state["anonymous_mode"] = bool(raw.get("anonymous_mode"))
    state["phase"] = _phase(raw.get("phase"))
    if state["enabled"] and state["phase"] == "signup":
        state["phase"] = "active"
    state["started_at"] = str(raw.get("started_at", "") or "")
    state["ended_at"] = str(raw.get("ended_at", "") or "")
    state["explicit_label"] = str(raw.get("explicit_label", "F%$@") or "F%$@")[:24]
    normalized_rounds = []
    seen_rounds: set[str] = set()
    raw_rounds = raw.get("rounds", [])
    if isinstance(raw_rounds, list):
        for index, raw_round in enumerate(raw_rounds[:MMF_ROUND_COUNT]):
            game_round = normalize_mmf_round(raw_round, index)
            if game_round and game_round["id"] not in seen_rounds:
                normalized_rounds.append(game_round)
                seen_rounds.add(game_round["id"])
    state["rounds"] = normalized_rounds or copy.deepcopy(DEFAULT_MMF_ROUNDS)
    valid_rounds = {entry["id"]: {person["id"] for person in entry["people"]} for entry in state["rounds"]}
    participants = {}
    raw_participants = raw.get("participants", {})
    if isinstance(raw_participants, dict):
        for user_id, raw_participant in raw_participants.items():
            participant = normalize_alias_participant(raw_participant, str(user_id), include_answers=True, valid_rounds=valid_rounds)
            if participant:
                participants[str(user_id)] = participant
    state["participants"] = participants
    state["results"] = calculate_mmf_results(state, finalized_at=str(raw.get("results", {}).get("finalized_at", "") if isinstance(raw.get("results"), dict) else "")) if state["phase"] == "ended" else copy.deepcopy(state["results"])
    state["presentation"] = _presentation(raw.get("presentation"))
    state["simulation"] = _simulation(raw.get("simulation"))
    return state


def normalize_prompt_record(raw: object, game_key: str, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = normalize_prompt(raw.get("text"))
    if not text or (game_key == FILL_BLANK_GAME_KEY and "___" not in text):
        return None
    return {"id": _slug_id(raw.get("id"), f"{game_key}-{index + 1:02d}"), "text": text, "enabled": bool(raw.get("enabled", True))}


def normalize_prompt_automation(raw: object, *, legacy: bool = False) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    try:
        remaining_seconds = max(0, int(source.get("remaining_seconds", 0) or 0))
    except (TypeError, ValueError):
        remaining_seconds = 0
    fingerprints = source.get("recent_prompt_fingerprints", [])
    return {
        # Existing live games migrate paused so deployment never advances them unexpectedly.
        "enabled": bool(source.get("enabled", not legacy)),
        "paused": bool(source.get("paused", legacy)),
        "paused_at": str(source.get("paused_at", "") or ""),
        "remaining_seconds": min(PROMPT_RESPONSE_WINDOW_SECONDS, remaining_seconds),
        "recent_prompt_fingerprints": [
            str(value)[:40] for value in fingerprints if value
        ][-PROMPT_RECENT_FINGERPRINT_LIMIT:] if isinstance(fingerprints, list) else [],
        "generator_version": PROMPT_GENERATOR_VERSION,
    }


def finalize_prompt_round(game_round: dict[str, Any]) -> dict[str, Any]:
    responses = game_round.get("responses", {})
    votes = game_round.get("votes", {})
    counts = {response_id: 0 for response_id in responses}
    for response_id in votes.values():
        if response_id in counts:
            counts[response_id] += 1
    top = max(counts.values(), default=0)
    solo_spotlight = len(responses) == 1 and not votes
    winner_response_ids = (
        list(responses)
        if solo_spotlight
        else sorted(response_id for response_id, count in counts.items() if top > 0 and count == top)
    )
    return {
        "vote_counts": counts,
        "winner_response_ids": winner_response_ids,
        "vote_count": sum(counts.values()),
        "solo_spotlight": solo_spotlight,
    }


def _iso_datetime(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _at_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def create_automatic_prompt_round(
    game_key: str,
    game: dict[str, Any],
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    timestamp = now or datetime.now(timezone.utc)
    generated = generate_prompt_for_game(game_key, game, rng=rng)
    round_id = uuid4().hex
    game_round = {
        "id": round_id,
        "prompt_id": "",
        "prompt_text": generated["text"],
        "prompt_source": generated["source"],
        "prompt_fingerprint": generated["fingerprint"],
        "generator_version": generated["generator_version"],
        "status": "submissions",
        "responses": {},
        "votes": {},
        "results": {"vote_counts": {}, "winner_response_ids": [], "vote_count": 0, "solo_spotlight": False},
        "created_at": _at_iso(timestamp),
        "phase_started_at": _at_iso(timestamp),
        "threshold_reached_at": "",
        "deadline_at": "",
        "voting_opened_at": "",
        "vote_extensions": 0,
        "revealed_at": "",
        "closed_at": "",
    }
    game.setdefault("rounds", []).append(game_round)
    game["current_round_id"] = round_id
    return game_round


def advance_prompt_game_automation(
    game_key: str,
    game: dict[str, Any],
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> list[str]:
    """Advance one prompt game at most one timed phase per call."""
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    automation = game.get("automation", {})
    if (
        game_key not in PROMPT_GAME_KEYS
        or not game.get("enabled")
        or game.get("phase") != "active"
        or not isinstance(automation, dict)
        or not automation.get("enabled")
        or automation.get("paused")
    ):
        return []

    current = prompt_round_for_game(game)
    if not current:
        create_automatic_prompt_round(game_key, game, now=timestamp, rng=rng)
        return ["round_opened"]

    status = str(current.get("status", "submissions"))
    deadline = _iso_datetime(current.get("deadline_at"))
    if status == "submissions":
        responses = current.get("responses", {})
        if len(responses) >= PROMPT_RESPONSE_MINIMUM and not deadline:
            current["threshold_reached_at"] = _at_iso(timestamp)
            current["phase_started_at"] = _at_iso(timestamp)
            current["deadline_at"] = _at_iso(timestamp + timedelta(seconds=PROMPT_RESPONSE_WINDOW_SECONDS))
            return ["response_timer_started"]
        if deadline and deadline <= timestamp:
            current["status"] = "voting"
            current["phase_started_at"] = _at_iso(timestamp)
            current["voting_opened_at"] = _at_iso(timestamp)
            current["deadline_at"] = _at_iso(timestamp + timedelta(seconds=PROMPT_VOTING_WINDOW_SECONDS))
            return ["voting_opened"]
        return []

    if status == "voting" and deadline and deadline <= timestamp:
        if not current.get("votes"):
            current["vote_extensions"] = _nonnegative_int(current.get("vote_extensions")) + 1
            current["phase_started_at"] = _at_iso(timestamp)
            current["deadline_at"] = _at_iso(timestamp + timedelta(seconds=PROMPT_VOTING_WINDOW_SECONDS))
            return ["voting_extended"]
        current["status"] = "revealed"
        current["revealed_at"] = _at_iso(timestamp)
        current["closed_at"] = _at_iso(timestamp)
        current["phase_started_at"] = _at_iso(timestamp)
        current["deadline_at"] = _at_iso(timestamp + timedelta(seconds=PROMPT_REVEAL_WINDOW_SECONDS))
        current["results"] = finalize_prompt_round(current)
        return ["round_revealed"]

    if status == "revealed" and deadline and deadline <= timestamp:
        create_automatic_prompt_round(game_key, game, now=timestamp, rng=rng)
        return ["round_opened"]
    return []


def calculate_prompt_results(game: dict[str, Any], *, finalized_at: str | None = None) -> dict[str, Any]:
    participants = game.get("participants", {})
    anonymous_mode = bool(game.get("anonymous_mode"))
    scores_by_player = {str(entry.get("player_id")): 0 for entry in participants.values()}
    identities = {
        str(entry.get("player_id")): {
            "name": participant_public_name(entry, anonymous=anonymous_mode),
            "alias": str(entry.get("alias", "Player")),
            "anonymous": anonymous_mode,
        }
        for entry in participants.values()
    }
    for game_round in game.get("rounds", []):
        if game_round.get("status") != "revealed":
            continue
        results = game_round.get("results", {})
        for response_id, votes in results.get("vote_counts", {}).items():
            response = game_round.get("responses", {}).get(response_id, {})
            player_id = str(response.get("player_id", ""))
            if player_id in scores_by_player:
                scores_by_player[player_id] += _nonnegative_int(votes)
        if results.get("solo_spotlight"):
            winner_ids = results.get("winner_response_ids", [])
            if winner_ids:
                response = game_round.get("responses", {}).get(winner_ids[0], {})
                player_id = str(response.get("player_id", ""))
                if player_id in scores_by_player:
                    scores_by_player[player_id] += 1
    scores = [
        {
            "player_id": player_id,
            "name": identities.get(player_id, {}).get("name", "Player"),
            "alias": identities.get(player_id, {}).get("alias", "Player"),
            "anonymous": bool(identities.get(player_id, {}).get("anonymous", True)),
            "points": points,
        }
        for player_id, points in scores_by_player.items()
    ]
    scores.sort(key=lambda entry: (-entry["points"], entry["name"].casefold()))
    top = scores[0]["points"] if scores else 0
    return {"finalized_at": finalized_at or utc_now_iso(), "scores": scores, "winner_player_ids": [entry["player_id"] for entry in scores if top > 0 and entry["points"] == top]}


def normalize_prompt_game_state(raw: object, game_key: str) -> dict[str, Any]:
    state = empty_prompt_game_state(game_key)
    if not isinstance(raw, dict):
        return state
    state["enabled"] = bool(raw.get("enabled"))
    state["anonymous_mode"] = bool(raw.get("anonymous_mode"))
    state["phase"] = _phase(raw.get("phase"))
    if state["enabled"] and state["phase"] == "signup":
        state["phase"] = "active"
    state["started_at"] = str(raw.get("started_at", "") or "")
    state["ended_at"] = str(raw.get("ended_at", "") or "")
    state["automation"] = normalize_prompt_automation(
        raw.get("automation"),
        legacy="automation" not in raw,
    )
    prompts = []
    seen_prompt_ids: set[str] = set()
    raw_prompts = raw.get("prompts", [])
    if isinstance(raw_prompts, list):
        for index, raw_prompt in enumerate(raw_prompts):
            prompt = normalize_prompt_record(raw_prompt, game_key, index)
            if prompt and prompt["id"] not in seen_prompt_ids:
                prompts.append(prompt)
                seen_prompt_ids.add(prompt["id"])
    state["prompts"] = prompts or default_prompt_records(game_key)
    participants = {}
    raw_participants = raw.get("participants", {})
    if isinstance(raw_participants, dict):
        for user_id, raw_participant in raw_participants.items():
            participant = normalize_alias_participant(raw_participant, str(user_id))
            if participant:
                participants[str(user_id)] = participant
    state["participants"] = participants
    valid_player_ids = {entry["player_id"] for entry in participants.values()}
    rounds = []
    seen_round_ids: set[str] = set()
    raw_rounds = raw.get("rounds", [])
    if isinstance(raw_rounds, list):
        for index, raw_round in enumerate(raw_rounds):
            if not isinstance(raw_round, dict):
                continue
            round_id = str(raw_round.get("id", "") or f"round-{index + 1}")[:80]
            prompt_text = normalize_prompt(raw_round.get("prompt_text"))
            status = str(raw_round.get("status", "submissions") or "submissions")
            if not prompt_text or status not in PROMPT_ROUND_PHASES or round_id in seen_round_ids:
                continue
            responses = {}
            raw_responses = raw_round.get("responses", {})
            if isinstance(raw_responses, dict):
                for response_id, raw_response in raw_responses.items():
                    if not isinstance(raw_response, dict):
                        continue
                    player_id = str(raw_response.get("player_id", "") or "")
                    text = normalize_response(raw_response.get("text"))
                    if player_id in valid_player_ids and text:
                        responses[str(response_id)] = {
                            "id": str(response_id),
                            "player_id": player_id,
                            "text": text,
                            "submitted_at": str(raw_response.get("submitted_at", "") or ""),
                            "display_hidden": bool(raw_response.get("display_hidden")),
                        }
            votes = {}
            raw_votes = raw_round.get("votes", {})
            if isinstance(raw_votes, dict):
                for player_id, response_id in raw_votes.items():
                    response = responses.get(str(response_id))
                    if str(player_id) in valid_player_ids and response and response.get("player_id") != str(player_id):
                        votes[str(player_id)] = str(response_id)
            game_round = {
                "id": round_id,
                "prompt_id": str(raw_round.get("prompt_id", "") or ""),
                "prompt_text": prompt_text,
                "prompt_source": str(raw_round.get("prompt_source", "manual") or "manual")[:24],
                "prompt_fingerprint": str(raw_round.get("prompt_fingerprint", "") or prompt_fingerprint(prompt_text))[:40],
                "generator_version": _nonnegative_int(raw_round.get("generator_version")),
                "status": status,
                "responses": responses,
                "votes": votes,
                "created_at": str(raw_round.get("created_at", "") or ""),
                "phase_started_at": str(raw_round.get("phase_started_at", "") or raw_round.get("created_at", "") or ""),
                "threshold_reached_at": str(raw_round.get("threshold_reached_at", "") or ""),
                "deadline_at": str(raw_round.get("deadline_at", "") or ""),
                "voting_opened_at": str(raw_round.get("voting_opened_at", "") or ""),
                "vote_extensions": _nonnegative_int(raw_round.get("vote_extensions")),
                "revealed_at": str(raw_round.get("revealed_at", "") or ""),
                "closed_at": str(raw_round.get("closed_at", "") or raw_round.get("revealed_at", "") or ""),
            }
            game_round["results"] = finalize_prompt_round(game_round) if status == "revealed" else {"vote_counts": {}, "winner_response_ids": [], "vote_count": 0, "solo_spotlight": False}
            rounds.append(game_round)
            seen_round_ids.add(round_id)
    state["rounds"] = rounds
    current_round_id = str(raw.get("current_round_id", "") or "")
    state["current_round_id"] = current_round_id if current_round_id in seen_round_ids else ""
    state["results"] = calculate_prompt_results(state, finalized_at=str(raw.get("results", {}).get("finalized_at", "") if isinstance(raw.get("results"), dict) else "")) if state["phase"] == "ended" else copy.deepcopy(state["results"])
    state["presentation"] = _presentation(raw.get("presentation"))
    state["simulation"] = _simulation(raw.get("simulation"))
    return state


def normalize_cursed_objectives_game_state(raw: object) -> dict[str, Any]:
    state = empty_cursed_objectives_game_state()
    if not isinstance(raw, dict):
        return state
    state["enabled"] = bool(raw.get("enabled"))
    state["phase"] = _phase(raw.get("phase"))
    if state["enabled"] and state["phase"] == "signup":
        state["phase"] = "active"
    state["started_at"] = str(raw.get("started_at", "") or "")
    state["ended_at"] = str(raw.get("ended_at", "") or "")

    objectives = []
    seen_objective_ids: set[str] = set()
    raw_objectives = raw.get("objectives", [])
    if isinstance(raw_objectives, list):
        for index, entry in enumerate(raw_objectives):
            if not isinstance(entry, dict):
                continue
            objective_id = _slug_id(entry.get("id"), f"cursed-objective-{index + 1:02d}")
            text = normalize_statement(entry.get("text"))
            if text and objective_id not in seen_objective_ids:
                objectives.append({"id": objective_id, "text": text, "enabled": bool(entry.get("enabled", True))})
                seen_objective_ids.add(objective_id)
    state["objectives"] = objectives or default_cursed_objective_records()
    valid_objective_ids = {entry["id"] for entry in state["objectives"]}

    participants = {}
    globally_assigned: set[str] = set()
    raw_participants = raw.get("participants", {})
    if isinstance(raw_participants, dict):
        for user_id, raw_participant in raw_participants.items():
            participant = normalize_alias_participant(raw_participant, str(user_id))
            if not participant:
                continue
            raw_mission_ids = raw_participant.get("mission_ids", []) if isinstance(raw_participant, dict) else []
            mission_ids = list(dict.fromkeys(
                str(value)
                for value in raw_mission_ids
                if str(value) in valid_objective_ids and str(value) not in globally_assigned
            ))[:CURSED_OBJECTIVES_PER_PLAYER]
            for objective in state["objectives"]:
                objective_id = str(objective["id"])
                if len(mission_ids) >= CURSED_OBJECTIVES_PER_PLAYER:
                    break
                if objective.get("enabled") and objective_id not in globally_assigned and objective_id not in mission_ids:
                    mission_ids.append(objective_id)
            if not mission_ids:
                continue
            globally_assigned.update(mission_ids)
            raw_completed = raw_participant.get("completed_mission_ids", [])
            completed = [str(value) for value in raw_completed if str(value) in mission_ids] if isinstance(raw_completed, list) else []
            completed_at = raw_participant.get("completed_at", {})
            participant["mission_ids"] = mission_ids
            participant["completed_mission_ids"] = list(dict.fromkeys(completed))
            participant["completed_at"] = {
                mission_id: str(completed_at.get(mission_id, "") or "")
                for mission_id in participant["completed_mission_ids"]
            } if isinstance(completed_at, dict) else {}
            participants[str(user_id)] = participant
    state["participants"] = participants
    state["results"] = (
        calculate_cursed_objectives_results(
            state,
            finalized_at=str(raw.get("results", {}).get("finalized_at", "") if isinstance(raw.get("results"), dict) else ""),
        )
        if state["phase"] == "ended"
        else copy.deepcopy(state["results"])
    )
    state["presentation"] = _presentation(raw.get("presentation"))
    state["simulation"] = _simulation(raw.get("simulation"))
    return state


def assign_cursed_objectives(
    game: dict[str, Any],
    user_id: str,
    *,
    display_name: str,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    existing = game.get("participants", {}).get(user_id)
    if isinstance(existing, dict):
        existing["display_name"] = normalize_player_name(display_name)
        existing["alias"] = existing["display_name"] or str(existing.get("alias", "Player"))
        existing["updated_at"] = utc_now_iso()
        return existing
    assigned = {
        str(mission_id)
        for participant in game.get("participants", {}).values()
        if isinstance(participant, dict)
        for mission_id in participant.get("mission_ids", [])
    }
    available = [
        str(objective.get("id", ""))
        for objective in game.get("objectives", [])
        if isinstance(objective, dict)
        and objective.get("enabled")
        and objective.get("id")
        and str(objective.get("id")) not in assigned
    ]
    if len(available) < CURSED_OBJECTIVES_PER_PLAYER:
        raise ValueError("No complete set of unused objectives remains.")
    chooser = rng or random.SystemRandom()
    mission_ids = chooser.sample(available, CURSED_OBJECTIVES_PER_PLAYER)
    timestamp = utc_now_iso()
    participant = {
        "player_id": uuid4().hex,
        "display_name": normalize_player_name(display_name),
        "alias": normalize_player_name(display_name) or "Player",
        "mission_ids": mission_ids,
        "completed_mission_ids": [],
        "completed_at": {},
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    game.setdefault("participants", {})[user_id] = participant
    return participant


def calculate_cursed_objectives_results(game: dict[str, Any], *, finalized_at: str | None = None) -> dict[str, Any]:
    scores = []
    for participant in game.get("participants", {}).values():
        if not isinstance(participant, dict):
            continue
        mission_ids = list(dict.fromkeys(str(value) for value in participant.get("mission_ids", [])))
        completed_ids = {
            str(value) for value in participant.get("completed_mission_ids", [])
            if str(value) in mission_ids
        }
        scores.append(
            {
                "player_id": str(participant.get("player_id", "")),
                "name": normalize_player_name(participant.get("display_name")) or "Player",
                "points": len(completed_ids),
                "completed_missions": len(completed_ids),
                "assigned_missions": len(mission_ids),
            }
        )
    scores.sort(key=lambda entry: (-entry["points"], entry["name"].casefold()))
    top = scores[0]["points"] if scores else 0
    return {
        "finalized_at": finalized_at or utc_now_iso(),
        "scores": scores,
        "winner_player_ids": [entry["player_id"] for entry in scores if top > 0 and entry["points"] == top],
    }


def cursed_objectives_statistics(game: dict[str, Any]) -> dict[str, Any]:
    participants = game.get("participants", {})
    completed = sum(
        len(set(participant.get("completed_mission_ids", [])))
        for participant in participants.values()
        if isinstance(participant, dict)
    )
    assigned = sum(
        len(participant.get("mission_ids", []))
        for participant in participants.values()
        if isinstance(participant, dict)
    )
    provisional = calculate_cursed_objectives_results(game, finalized_at="")
    return {
        "participant_count": len(participants),
        "completed_missions": completed,
        "assigned_missions": assigned,
        "completion_percent": round((completed / assigned * 100) if assigned else 0.0, 1),
        "available_objectives": max(0, sum(1 for entry in game.get("objectives", []) if entry.get("enabled")) - assigned),
        "scores": provisional["scores"],
    }


def normalize_games_state(raw: object) -> dict[str, Any]:
    raw_games = raw if isinstance(raw, dict) else {}
    return {
        TWO_TRUTHS_GAME_KEY: normalize_two_truths_game_state(raw_games.get(TWO_TRUTHS_GAME_KEY)),
        MURDER_MARRY_FUCK_GAME_KEY: normalize_mmf_game_state(raw_games.get(MURDER_MARRY_FUCK_GAME_KEY)),
        **{game_key: normalize_prompt_game_state(raw_games.get(game_key), game_key) for game_key in PROMPT_GAME_KEYS},
        CURSED_OBJECTIVES_GAME_KEY: normalize_cursed_objectives_game_state(raw_games.get(CURSED_OBJECTIVES_GAME_KEY)),
    }


def participant_statements(participant: dict[str, Any]) -> list[str]:
    statements = [*participant.get("truths", []), participant.get("lie", "")]
    order = participant.get("display_order", [0, 1, 2])
    return [str(statements[index]) for index in order if index in {0, 1, 2}]


def calculate_two_truths_results(game: dict[str, Any], *, finalized_at: str | None = None) -> dict[str, Any]:
    participants = game.get("participants", {})
    guesses = game.get("guesses", {})
    targets_by_submission = {participant["submission_id"]: participant for participant in participants.values()}
    scores = []
    target_totals = {submission_id: {"guess_count": 0, "correct_guesses": 0} for submission_id in targets_by_submission}
    for guesser_id, guesser in participants.items():
        submission_guesses = guesses.get(guesser_id, {})
        attempts = 0
        correct = 0
        for submission_id, guess in submission_guesses.items():
            target = targets_by_submission.get(submission_id)
            if not target or target.get("user_id") == guesser_id:
                continue
            attempts += 1
            target_totals[submission_id]["guess_count"] += 1
            is_correct = guess.get("normalized_name") == normalize_guess_name(target.get("answer_name"))
            if is_correct:
                correct += 1
                target_totals[submission_id]["correct_guesses"] += 1
        scores.append({"user_id": guesser_id, "name": guesser.get("answer_name", "Guest"), "correct": correct, "attempts": attempts, "accuracy": round((correct / attempts * 100) if attempts else 0.0, 1)})
    scores.sort(key=lambda entry: (-entry["correct"], -entry["accuracy"], entry["name"].casefold()))
    top_score = scores[0]["correct"] if scores else 0
    winner_ids = [entry["user_id"] for entry in scores if top_score > 0 and entry["correct"] == top_score]
    participant_results = [{"submission_id": submission_id, "name": target.get("answer_name", "Guest"), **target_totals[submission_id]} for submission_id, target in targets_by_submission.items()]
    participant_results.sort(key=lambda entry: entry["name"].casefold())
    return {"finalized_at": finalized_at or utc_now_iso(), "scores": scores, "winner_ids": winner_ids, "participant_results": participant_results}


def two_truths_statistics(game: dict[str, Any]) -> dict[str, Any]:
    participants = game.get("participants", {})
    guesses = game.get("guesses", {})
    provisional = calculate_two_truths_results(game, finalized_at="")
    possible_guesses = max(0, len(participants) * max(0, len(participants) - 1))
    submitted_guesses = sum(len(entries) for entries in guesses.values())
    matched_guesses = sum(entry["correct"] for entry in provisional["scores"])
    return {"participant_count": len(participants), "guesser_count": sum(1 for entries in guesses.values() if entries), "submitted_guesses": submitted_guesses, "possible_guesses": possible_guesses, "completion_percent": round((submitted_guesses / possible_guesses * 100) if possible_guesses else 0.0, 1), "correct_guesses": matched_guesses, "incorrect_guesses": max(0, submitted_guesses - matched_guesses), "scores": provisional["scores"], "participant_results": provisional["participant_results"]}


def mmf_statistics(game: dict[str, Any]) -> dict[str, Any]:
    participants = game.get("participants", {})
    round_count = len(game.get("rounds", []))
    completed = sum(len(entry.get("answers", {})) for entry in participants.values())
    possible = len(participants) * round_count
    provisional = calculate_mmf_results(game, finalized_at="")
    return {"participant_count": len(participants), "completed_rounds": completed, "possible_rounds": possible, "completion_percent": round((completed / possible * 100) if possible else 0.0, 1), "scores": provisional["scores"], "round_results": provisional["round_results"]}


def prompt_game_statistics(game: dict[str, Any]) -> dict[str, Any]:
    rounds = game.get("rounds", [])
    current_id = str(game.get("current_round_id", ""))
    current = next((entry for entry in rounds if entry.get("id") == current_id), None)
    results = calculate_prompt_results(game, finalized_at="")
    return {"participant_count": len(game.get("participants", {})), "round_count": len(rounds), "response_count": len(current.get("responses", {})) if current else 0, "vote_count": len(current.get("votes", {})) if current else 0, "current_round": current, "scores": results["scores"]}


def game_by_slug(slug: str) -> str | None:
    return GAME_KEY_BY_SLUG.get(str(slug or ""))


def game_winners(game_key: str, game: dict[str, Any]) -> list[dict[str, Any]]:
    results = game.get("results", {})
    if game_key == TWO_TRUTHS_GAME_KEY:
        winner_ids = set(results.get("winner_ids", []))
        return [entry for entry in results.get("scores", []) if entry.get("user_id") in winner_ids]
    winner_ids = set(results.get("winner_player_ids", []))
    return [entry for entry in results.get("scores", []) if entry.get("player_id") in winner_ids]


def prompt_round_for_game(game: dict[str, Any]) -> dict[str, Any] | None:
    current_id = str(game.get("current_round_id", ""))
    return next((entry for entry in game.get("rounds", []) if entry.get("id") == current_id), None)


def build_simulated_game_state(
    game_key: str,
    current_game: dict[str, Any],
    *,
    player_count: int = 8,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build deterministic, completed test data without creating party accounts."""
    if game_key not in GAME_CATALOG:
        raise KeyError(game_key)
    count = min(20, max(2, int(player_count)))
    timestamp = generated_at or utc_now_iso()
    simulation = {"is_simulated": True, "player_count": count, "generated_at": timestamp}

    if game_key == TWO_TRUTHS_GAME_KEY:
        game = empty_two_truths_game_state(enabled=True)
        for index in range(count):
            number = index + 1
            user_id = f"simulation:{game_key}:player-{number:02d}"
            game["participants"][user_id] = {
                "user_id": user_id,
                "submission_id": f"simulation-two-truths-{number:02d}",
                "answer_name": f"Test Player {number:02d}",
                "truths": [
                    f"I have attended {number} costume parties.",
                    f"My lucky number is {number * 3}.",
                ],
                "lie": f"I keep {number + 2} pet ghosts at home.",
                "display_order": [index % 3, (index + 1) % 3, (index + 2) % 3],
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        participants = list(game["participants"].items())
        for guesser_index, (guesser_id, _guesser) in enumerate(participants):
            guesses = {}
            for target_index, (target_id, target) in enumerate(participants):
                if target_id == guesser_id:
                    continue
                correct = guesser_index == 0 or (guesser_index + target_index) % 3 != 0
                guessed_name = target["answer_name"] if correct else f"Mystery Guest {target_index + 1:02d}"
                guesses[target["submission_id"]] = {
                    "guessed_name": guessed_name,
                    "normalized_name": normalize_guess_name(guessed_name),
                    "submitted_at": timestamp,
                }
            game["guesses"][guesser_id] = guesses
        game["phase"] = "ended"
        game["started_at"] = timestamp
        game["ended_at"] = timestamp
        game["results"] = calculate_two_truths_results(game, finalized_at=timestamp)
        game["simulation"] = simulation
        return game

    if game_key == MURDER_MARRY_FUCK_GAME_KEY:
        game = empty_mmf_game_state(enabled=True)
        game["anonymous_mode"] = bool(current_game.get("anonymous_mode"))
        configured_rounds = current_game.get("rounds", [])
        game["rounds"] = copy.deepcopy(configured_rounds if len(configured_rounds) == MMF_ROUND_COUNT else DEFAULT_MMF_ROUNDS)
        game["explicit_label"] = str(current_game.get("explicit_label", "F%$@") or "F%$@")[:24]
        for index in range(count):
            number = index + 1
            user_id = f"simulation:{game_key}:player-{number:02d}"
            answers = {}
            for round_index, game_round in enumerate(game["rounds"]):
                people = [str(person["id"]) for person in game_round["people"]]
                offset = (index + round_index) % 3
                answers[str(game_round["id"])] = {
                    "murder": people[offset],
                    "marry": people[(offset + 1) % 3],
                    "fuck": people[(offset + 2) % 3],
                }
            game["participants"][user_id] = {
                "player_id": f"simulation-player-{number:02d}",
                "display_name": f"Test Player {number:02d}",
                "alias": f"Test Alias {number:02d}",
                "answers": answers,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        game["phase"] = "ended"
        game["started_at"] = timestamp
        game["ended_at"] = timestamp
        game["results"] = calculate_mmf_results(game, finalized_at=timestamp)
        game["simulation"] = simulation
        return game

    if game_key == CURSED_OBJECTIVES_GAME_KEY:
        game = empty_cursed_objectives_game_state(enabled=True)
        objective_ids = [entry["id"] for entry in game["objectives"]]
        for index in range(count):
            number = index + 1
            start = index * CURSED_OBJECTIVES_PER_PLAYER
            mission_ids = objective_ids[start : start + CURSED_OBJECTIVES_PER_PLAYER]
            user_id = f"simulation:{game_key}:player-{number:02d}"
            completed_count = (index % CURSED_OBJECTIVES_PER_PLAYER) + 1
            game["participants"][user_id] = {
                "player_id": f"simulation-player-{number:02d}",
                "display_name": f"Test Player {number:02d}",
                "alias": f"Test Player {number:02d}",
                "mission_ids": mission_ids,
                "completed_mission_ids": mission_ids[:completed_count],
                "completed_at": {mission_id: timestamp for mission_id in mission_ids[:completed_count]},
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        game["phase"] = "ended"
        game["started_at"] = timestamp
        game["ended_at"] = timestamp
        game["results"] = calculate_cursed_objectives_results(game, finalized_at=timestamp)
        game["simulation"] = simulation
        return game

    game = empty_prompt_game_state(game_key, enabled=True)
    game["anonymous_mode"] = bool(current_game.get("anonymous_mode"))
    configured_prompts = current_game.get("prompts", [])
    game["prompts"] = copy.deepcopy(configured_prompts or default_prompt_records(game_key))
    for index in range(count):
        number = index + 1
        user_id = f"simulation:{game_key}:player-{number:02d}"
        game["participants"][user_id] = {
            "player_id": f"simulation-player-{number:02d}",
            "display_name": f"Test Player {number:02d}",
            "alias": f"Test Alias {number:02d}",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    simulation_prompts = [prompt for prompt in game["prompts"] if prompt.get("enabled")][:3]
    if not simulation_prompts:
        simulation_prompts = game["prompts"][:1]
    if not simulation_prompts:
        game["prompts"] = default_prompt_records(game_key)
        simulation_prompts = game["prompts"][:1]
    participant_items = list(game["participants"].items())
    for round_index, prompt in enumerate(simulation_prompts):
        round_id = f"simulation-{game_key}-round-{round_index + 1:02d}"
        responses = {}
        response_ids = []
        for player_index, (_user_id, participant) in enumerate(participant_items):
            response_id = f"{round_id}-response-{player_index + 1:02d}"
            response_ids.append(response_id)
            responses[response_id] = {
                "id": response_id,
                "player_id": participant["player_id"],
                "text": f"Simulated answer {player_index + 1} for round {round_index + 1}",
                "submitted_at": timestamp,
            }
        votes = {}
        for player_index, (_user_id, participant) in enumerate(participant_items):
            target_index = 1 if player_index == 0 else 0
            votes[participant["player_id"]] = response_ids[target_index]
        game_round = {
            "id": round_id,
            "prompt_id": str(prompt.get("id", "")),
            "prompt_text": str(prompt.get("text", "")),
            "status": "revealed",
            "responses": responses,
            "votes": votes,
            "created_at": timestamp,
            "revealed_at": timestamp,
        }
        game_round["results"] = finalize_prompt_round(game_round)
        game["rounds"].append(game_round)
    game["current_round_id"] = str(game["rounds"][-1]["id"])
    game["phase"] = "ended"
    game["started_at"] = timestamp
    game["ended_at"] = timestamp
    game["results"] = calculate_prompt_results(game, finalized_at=timestamp)
    game["simulation"] = simulation
    return game
