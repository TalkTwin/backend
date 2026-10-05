from pathlib import Path

from core.config import STORAGE_DIR


def _key_to_path(key: str) -> Path:
    return STORAGE_DIR / Path(key)


def voice_clip_path(voice_id: str, ext: str) -> tuple[Path, str]:
    rel = f"voices/{voice_id}/ref{ext}"
    return STORAGE_DIR / "voices" / voice_id / f"ref{ext}", rel


def voice_embedding_path(voice_id: str) -> tuple[Path, str]:
    rel = f"voices/{voice_id}/embedding.npy"
    return STORAGE_DIR / "voices" / voice_id / "embedding.npy", rel


def avatar_image_path(avatar_id: str, ext: str) -> tuple[Path, str]:
    rel = f"avatars/{avatar_id}/image{ext}"
    return STORAGE_DIR / "avatars" / avatar_id / f"image{ext}", rel


def avatar_latents_path(avatar_id: str) -> tuple[Path, str]:
    rel = f"avatars/{avatar_id}/latents.npy"
    return STORAGE_DIR / "avatars" / avatar_id / "latents.npy", rel


def job_result_path(job_id: str, ext: str) -> tuple[Path, str]:
    rel = f"jobs/{job_id}/result{ext}"
    return STORAGE_DIR / "jobs" / job_id / f"result{ext}", rel


def save_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def delete_key(key: str | None) -> None:
    if not key:
        return
    try:
        p = _key_to_path(key)
        p.unlink(missing_ok=True)
        # cleanup empty voice dir (voices/{id}) if both files gone
        parent = p.parent
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
    except OSError:
        pass
