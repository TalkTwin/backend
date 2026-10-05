# Single source of truth for supported languages (doc Sec 6.1: 13 required).
# Proposed default — confirm against the product spec; voices/tts validation
# will enforce against this list once confirmed (TODO).
LANGUAGES: list[dict[str, str]] = [
    {"code": "en", "name": "English"},
    {"code": "hi", "name": "Hindi"},
    {"code": "mr", "name": "Marathi"},
    {"code": "gu", "name": "Gujarati"},
    {"code": "ta", "name": "Tamil"},
    {"code": "te", "name": "Telugu"},
    {"code": "kn", "name": "Kannada"},
    {"code": "ml", "name": "Malayalam"},
    {"code": "bn", "name": "Bengali"},
    {"code": "pa", "name": "Punjabi"},
    {"code": "or", "name": "Odia"},
    {"code": "as", "name": "Assamese"},
    {"code": "ur", "name": "Urdu"},
]

LANGUAGE_CODES = frozenset(lang["code"] for lang in LANGUAGES)
