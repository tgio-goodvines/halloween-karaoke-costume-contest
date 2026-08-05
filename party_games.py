from __future__ import annotations

import copy
import re
import secrets
from datetime import datetime, timezone
from typing import Any


TWO_TRUTHS_GAME_KEY = "two_truths_and_a_lie"
MURDER_MARRY_FUCK_GAME_KEY = "murder_marry_fuck"
FILL_BLANK_GAME_KEY = "fill_in_the_blank"
BAD_ADVICE_GAME_KEY = "bad_advice_hotline"
WRONG_ANSWERS_GAME_KEY = "wrong_answers_only"
PROMPT_GAME_KEYS = (FILL_BLANK_GAME_KEY, BAD_ADVICE_GAME_KEY, WRONG_ANSWERS_GAME_KEY)
GAME_PHASES = {"signup", "active", "ended"}
PROMPT_ROUND_PHASES = {"submissions", "voting", "revealed"}
GAME_STATEMENT_MAX_LENGTH = 240
GAME_PROMPT_MAX_LENGTH = 240
GAME_RESPONSE_MAX_LENGTH = 280
MMF_ROUND_COUNT = 10
MMF_ACTIONS = ("murder", "marry", "fuck")


GAME_CATALOG: dict[str, dict[str, str]] = {
    TWO_TRUTHS_GAME_KEY: {
        "slug": "two-truths-and-a-lie",
        "title": "Two Truths and a Lie",
        "short_title": "Two Truths",
        "engine": "identity",
        "description": "Submit two truths and a lie, then identify the mystery guests.",
        "image": "images/games/two-truths-and-a-lie.jpg",
        "personality": "Three stories enter the lab. Only one is fabricated.",
        "solo_note": "Needs at least two mystery guests.",
    },
    MURDER_MARRY_FUCK_GAME_KEY: {
        "slug": "murder-marry-fuck",
        "title": "Murder, Marry, F%$@",
        "short_title": "Murder / Marry / F%$@",
        "engine": "choice",
        "description": "Assign three famous adults to three impossible choices across ten rounds.",
        "image": "images/games/murder-marry-fuck.jpg",
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
        "personality": "Accuracy is suspicious. Confidence earns the applause.",
        "solo_note": "Solo spotlight supported.",
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


def default_prompt_records(game_key: str) -> list[dict[str, Any]]:
    return [
        {"id": f"{game_key}-{index + 1:02d}", "text": text, "enabled": True}
        for index, text in enumerate(DEFAULT_PROMPTS.get(game_key, []))
    ]


def empty_two_truths_game_state(*, enabled: bool = False) -> dict[str, Any]:
    state = copy.deepcopy(DEFAULT_TWO_TRUTHS_GAME_STATE)
    state["enabled"] = bool(enabled)
    return state


def empty_mmf_game_state(*, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "phase": "signup",
        "started_at": "",
        "ended_at": "",
        "explicit_label": "F%$@",
        "rounds": copy.deepcopy(DEFAULT_MMF_ROUNDS),
        "participants": {},
        "results": {"finalized_at": "", "round_results": [], "scores": [], "winner_player_ids": []},
        "presentation": {"active": False, "slide_index": 0},
    }


def empty_prompt_game_state(game_key: str, *, enabled: bool = False) -> dict[str, Any]:
    return {
        "enabled": bool(enabled),
        "phase": "signup",
        "started_at": "",
        "ended_at": "",
        "participants": {},
        "prompts": default_prompt_records(game_key),
        "rounds": [],
        "current_round_id": "",
        "results": {"finalized_at": "", "scores": [], "winner_player_ids": []},
        "presentation": {"active": False, "slide_index": 0},
    }


DEFAULT_GAMES_STATE: dict[str, Any] = {
    TWO_TRUTHS_GAME_KEY: empty_two_truths_game_state(),
    MURDER_MARRY_FUCK_GAME_KEY: empty_mmf_game_state(),
    **{game_key: empty_prompt_game_state(game_key) for game_key in PROMPT_GAME_KEYS},
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
    alias = re.sub(r"\s+", " ", str(raw.get("alias", "") or "").strip())[:80]
    if not user_id or not player_id or not alias:
        return None
    participant = {"player_id": player_id, "alias": alias, "created_at": str(raw.get("created_at", "") or ""), "updated_at": str(raw.get("updated_at", "") or "")}
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
    scores_by_player = {str(entry.get("player_id")): 0 for entry in participants.values()}
    aliases = {str(entry.get("player_id")): str(entry.get("alias", "Player")) for entry in participants.values()}
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
    scores = [{"player_id": player_id, "alias": aliases.get(player_id, "Player"), "points": points, "completed_rounds": len(next((entry.get("answers", {}) for entry in participants.values() if str(entry.get("player_id")) == player_id), {}))} for player_id, points in scores_by_player.items()]
    scores.sort(key=lambda entry: (-entry["points"], entry["alias"].casefold()))
    top_score = scores[0]["points"] if scores else 0
    winner_player_ids = [entry["player_id"] for entry in scores if top_score > 0 and entry["points"] == top_score]
    return {"finalized_at": finalized_at or utc_now_iso(), "round_results": round_results, "scores": scores, "winner_player_ids": winner_player_ids}


def normalize_mmf_game_state(raw: object) -> dict[str, Any]:
    state = empty_mmf_game_state()
    if not isinstance(raw, dict):
        return state
    state["enabled"] = bool(raw.get("enabled"))
    state["phase"] = _phase(raw.get("phase"))
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
    return state


def normalize_prompt_record(raw: object, game_key: str, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    text = normalize_prompt(raw.get("text"))
    if not text or (game_key == FILL_BLANK_GAME_KEY and "___" not in text):
        return None
    return {"id": _slug_id(raw.get("id"), f"{game_key}-{index + 1:02d}"), "text": text, "enabled": bool(raw.get("enabled", True))}


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


def calculate_prompt_results(game: dict[str, Any], *, finalized_at: str | None = None) -> dict[str, Any]:
    participants = game.get("participants", {})
    scores_by_player = {str(entry.get("player_id")): 0 for entry in participants.values()}
    aliases = {str(entry.get("player_id")): str(entry.get("alias", "Player")) for entry in participants.values()}
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
    scores = [{"player_id": player_id, "alias": aliases.get(player_id, "Player"), "points": points} for player_id, points in scores_by_player.items()]
    scores.sort(key=lambda entry: (-entry["points"], entry["alias"].casefold()))
    top = scores[0]["points"] if scores else 0
    return {"finalized_at": finalized_at or utc_now_iso(), "scores": scores, "winner_player_ids": [entry["player_id"] for entry in scores if top > 0 and entry["points"] == top]}


def normalize_prompt_game_state(raw: object, game_key: str) -> dict[str, Any]:
    state = empty_prompt_game_state(game_key)
    if not isinstance(raw, dict):
        return state
    state["enabled"] = bool(raw.get("enabled"))
    state["phase"] = _phase(raw.get("phase"))
    state["started_at"] = str(raw.get("started_at", "") or "")
    state["ended_at"] = str(raw.get("ended_at", "") or "")
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
                        responses[str(response_id)] = {"id": str(response_id), "player_id": player_id, "text": text, "submitted_at": str(raw_response.get("submitted_at", "") or "")}
            votes = {}
            raw_votes = raw_round.get("votes", {})
            if isinstance(raw_votes, dict):
                for player_id, response_id in raw_votes.items():
                    response = responses.get(str(response_id))
                    if str(player_id) in valid_player_ids and response and response.get("player_id") != str(player_id):
                        votes[str(player_id)] = str(response_id)
            game_round = {"id": round_id, "prompt_id": str(raw_round.get("prompt_id", "") or ""), "prompt_text": prompt_text, "status": status, "responses": responses, "votes": votes, "created_at": str(raw_round.get("created_at", "") or ""), "revealed_at": str(raw_round.get("revealed_at", "") or "")}
            game_round["results"] = finalize_prompt_round(game_round) if status == "revealed" else {"vote_counts": {}, "winner_response_ids": [], "vote_count": 0}
            rounds.append(game_round)
            seen_round_ids.add(round_id)
    state["rounds"] = rounds
    current_round_id = str(raw.get("current_round_id", "") or "")
    state["current_round_id"] = current_round_id if current_round_id in seen_round_ids else ""
    state["results"] = calculate_prompt_results(state, finalized_at=str(raw.get("results", {}).get("finalized_at", "") if isinstance(raw.get("results"), dict) else "")) if state["phase"] == "ended" else copy.deepcopy(state["results"])
    state["presentation"] = _presentation(raw.get("presentation"))
    return state


def normalize_games_state(raw: object) -> dict[str, Any]:
    raw_games = raw if isinstance(raw, dict) else {}
    return {
        TWO_TRUTHS_GAME_KEY: normalize_two_truths_game_state(raw_games.get(TWO_TRUTHS_GAME_KEY)),
        MURDER_MARRY_FUCK_GAME_KEY: normalize_mmf_game_state(raw_games.get(MURDER_MARRY_FUCK_GAME_KEY)),
        **{game_key: normalize_prompt_game_state(raw_games.get(game_key), game_key) for game_key in PROMPT_GAME_KEYS},
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
