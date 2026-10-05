# infra read (doc 9.3): supported languages for Studio dropdowns. Open, no auth.
from fastapi import APIRouter

from core.languages import LANGUAGES

router = APIRouter(tags=["infra"])


@router.get("/languages", response_model=list[dict[str, str]],
            summary="Supported languages", description="The 13 product languages (code + name).")
def list_languages():
    return LANGUAGES
