"""Deterministic life-threat lexicon and vetted step library (KAN-50, LR 08 SEC-01/SEC-03/SEC-11).

The deterministic floor: if any condition below matches the (normalised) incident text, urgency is
CRITICAL and a simulated call_emergency_services action is mandatory, whatever any model says.
Displayed safety steps come ONLY from STEP_LIBRARY; model free text is never shown as instructions.
"""

from __future__ import annotations

import re
import unicodedata

_W = r"(?<![a-z])"  # left word boundary that tolerates prefixes like "self-"

# condition id -> pattern (applied to normalise_text() output)
LIFE_THREAT_CONDITIONS: dict[str, re.Pattern[str]] = {
    "self_harm": re.compile(
        _W
        + r"(suicid\w*|kill (myself|himself|herself|themselves)|end (my|his|her) life|"
        r"self[- ]?harm\w*|cut(ting)? (myself|my wrists?)|want to die|take my (own )?life|overdos\w* on purpose)"
    ),
    "overdose_poisoning": re.compile(
        _W
        + r"(overdos\w*|took (too many|a bottle of|all (my|the|her|his)) (pills|tablets|medication)|"
        r"poison\w*|swallowed (bleach|chemicals?|pills|battery|detergent)|opioid|fentanyl|heroin)"
    ),
    "seizure": re.compile(_W + r"(seizure\w*|convuls\w*|fitting|epileptic fit)"),
    "drowning": re.compile(
        _W
        + r"(drown\w*|pulled from (the )?(water|pool)|face ?down in (the )?(water|pool))"
    ),
    "not_breathing": re.compile(
        _W + r"(not breathing|isn'?t breathing|stopped breathing|no pulse|no heartbeat|"
        r"cannot breathe|can'?t breathe|difficulty breathing|struggling to breathe|shortness of breath|"
        r"turning blue|cyanosis|suffocat\w*)"
    ),
    "choking": re.compile(
        _W + r"(chok\w*|something stuck in (his|her|my|their) throat)"
    ),
    "unconscious": re.compile(
        _W
        + r"(unconscious|unresponsive|not responding|won'?t wake( up)?|passed out|fainted|collapsed|"
        r"not waking)"
    ),
    "cardiac": re.compile(
        _W + r"(chest pain|chest pressure|chest tightness|heart attack|cardiac|angina)"
    ),
    "severe_bleeding": re.compile(
        _W
        + r"(severe bleeding|bleeding heavily|heavy bleeding|bleeding (a lot|badly|won'?t stop)|"
        r"hemorrhag\w*|haemorrhag\w*|arterial|gushing blood|spurting blood)"
    ),
    "stroke": re.compile(
        _W
        + r"(stroke|face (is )?droop\w*|facial droop\w*|slurred speech|sudden numbness|"
        r"one side (of (his|her|my) body )?(is )?(weak|numb|paralys\w*)|paralys\w*|paralyz\w*)"
    ),
    "anaphylaxis": re.compile(
        _W
        + r"(anaphyla\w*|epipen|throat (is )?swelling|severe allergic reaction|tongue swelling)"
    ),
    "major_trauma": re.compile(
        _W
        + r"(stabbed|stab wound|been shot|gunshot|shot (in|at)|head trauma|skull fracture|"
        r"spinal injury|impaled|electrocut\w*|amputat\w*|crushed)"
    ),
    "obstetric": re.compile(
        _W
        + r"(in labou?r|water broke|pregnan\w* and bleeding|bleeding (while|and) pregnant)"
    ),
    "wildfire": re.compile(
        _W
        + r"(wildfire|wild fire|brush ?fire|bush ?fire|forest fire|grass fire|flame line|"
        r"evacuation order|fire (is )?(approaching|spreading toward))"
    ),
    "structure_fire": re.compile(
        _W
        + r"(house (is )?on fire|building (is )?on fire|fire trapped|trapped (by|in) (the )?(fire|smoke)|"
        r"smoke inhalation|severe burns?|building collapse|gas leak|explosion)"
    ),
}

GENERIC_CALL_STEP = "Call emergency services now (112 / 911 / your local number). This is a simulation and has NOT called anyone."

STEP_LIBRARY: dict[str, list[str]] = {
    "self_harm": [
        "Call emergency services now if you or someone is in immediate danger.",
        "Contact a crisis line now: 988 Suicide & Crisis Lifeline (US, call or text 988); India Tele-MANAS 14416 or 112; elsewhere your local emergency number.",
        "Stay with the person, or stay with someone you trust. Do not leave them alone.",
        "Remove access to pills, weapons, or other means of harm if it is safe to do so.",
    ],
    "overdose_poisoning": [
        "Check breathing. If not breathing normally, start CPR if trained and follow the dispatcher's instructions.",
        "If unconscious but breathing, place the person on their side (recovery position).",
        "Keep any pill bottles or containers to show responders. Do not induce vomiting unless told to by a professional.",
        "Contact a poison control center if available, while emergency services are on the way.",
    ],
    "seizure": [
        "Move hard or sharp objects away. Cushion the head. Do not restrain the person.",
        "Do not put anything in their mouth.",
        "Time the seizure. When it stops, place them on their side.",
    ],
    "drowning": [
        "Get the person out of the water only if it is safe for you to do so.",
        "Check breathing. If not breathing, start CPR if trained (for a child, follow the dispatcher's guidance).",
        "Keep them warm and on their side if breathing.",
    ],
    "not_breathing": [
        "If the person is not breathing normally, start CPR if trained, or follow the dispatcher's CPR instructions.",
        "Ask someone to find an AED (defibrillator) if one is nearby.",
    ],
    "choking": [
        "If they cannot cough, speak or breathe, give back blows and abdominal thrusts if trained.",
        "If they become unresponsive, start CPR and follow the dispatcher's instructions.",
    ],
    "unconscious": [
        "Check for breathing. If breathing, place them on their side (recovery position).",
        "If not breathing normally, start CPR if trained, or follow the dispatcher's instructions.",
    ],
    "cardiac": [
        "Keep the person still and seated in a comfortable position. Do not let them exert themselves.",
        "Loosen tight clothing. Ask someone to find an AED if one is nearby.",
        "If they become unresponsive and stop breathing normally, start CPR if trained.",
    ],
    "severe_bleeding": [
        "Apply firm, continuous pressure to the wound with a clean cloth.",
        "Do not remove embedded objects. Keep the person lying down and warm.",
    ],
    "stroke": [
        "Note the time symptoms started; tell the dispatcher.",
        "Keep the person comfortable and do not give food or drink.",
    ],
    "anaphylaxis": [
        "If the person has a prescribed adrenaline auto-injector, help them use it as directed on the device.",
        "Keep them sitting up if breathing is hard, or lying down if they feel faint.",
    ],
    "major_trauma": [
        "Do not move the person unless they are in immediate danger.",
        "Apply firm pressure to any bleeding. Keep them still and warm.",
    ],
    "obstetric": [
        "Have the person lie on their left side and stay calm.",
        "Follow the dispatcher's instructions.",
    ],
    "wildfire": [
        "Follow official evacuation orders immediately. Leave early; do not wait to see the fire.",
        "Use the planned evacuation route away from the fire and smoke; avoid roads blocked by flames or downed power lines.",
        "Take your go-bag (medications, documents, water, phone charger, N95 masks) only if it is ready.",
        "Close windows and doors behind you, wear long sleeves, and cover your nose and mouth against smoke.",
        "Tell your emergency contact where you are going; check local emergency alerts for shelter locations.",
    ],
    "structure_fire": [
        "Get out and stay out. Do not use elevators.",
        "Stay low under smoke. Check doors for heat before opening.",
        "Meet at your outdoor assembly point.",
    ],
    "accident": [
        "Turn on hazard lights and move to a safe place away from traffic if you can.",
        "Do not move seriously injured people unless there is fire or other immediate danger.",
        "Check for breathing and heavy bleeding; apply pressure to bleeding.",
    ],
    "general": [
        "Make sure you and others are safe from further danger.",
        "If anyone is in danger or seriously hurt, call emergency services now (112 / 911).",
        "Share your exact location and what happened when help answers.",
    ],
}

CATEGORY_TO_LIBRARY = {
    "accident": "accident",
    "fire_hazard": "structure_fire",
    "medical": "general",
}

# Unsafe advice that must never reach the user from any source (SEC-03).
UNSAFE_ADVICE = re.compile(
    r"(do ?n[o']?t|never|no need to|don'?t bother to) (call|phone|contact|dial) (an? )?(ambulance|911|112|999|emergency|doctor|paramedics?|help)"
    r"|sleep it off|wait (and see|it out|until morning)|induce vomiting|make (him|her|them|yourself) (vomit|throw up)"
    r"|\b(aspirin|ibuprofen|paracetamol|acetaminophen|tylenol|naloxone dose|\d+ ?mg)\b",
    re.IGNORECASE,
)

_APOS = str.maketrans(
    {"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u201c": '"', "\u201d": '"'}
)
_ZW = re.compile("[\u200b-\u200f\u2060\ufeff]")


def normalise_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = _ZW.sub("", t).translate(_APOS).lower()
    return re.sub(r"\s+", " ", t)


def detect_conditions(text: str) -> list[str]:
    t = normalise_text(text)
    return [cid for cid, pat in LIFE_THREAT_CONDITIONS.items() if pat.search(t)]


def vetted_steps(conditions: list[str], category: str, escalate: bool) -> list[str]:
    steps: list[str] = []
    if escalate:
        steps.append(GENERIC_CALL_STEP)
    keys = list(conditions) or [CATEGORY_TO_LIBRARY.get(category, "general")]
    for k in keys:
        for s in STEP_LIBRARY.get(k, []):
            if s not in steps:
                steps.append(s)
    return steps[:10]


def describe_conditions(text: str) -> str:
    t = normalise_text(text)
    parts = []
    for cid, pat in LIFE_THREAT_CONDITIONS.items():
        m = pat.search(t)
        if m:
            parts.append(f"{cid} ('{m.group(0)}')")
    return ", ".join(parts)
