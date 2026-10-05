import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import SessionLocal
from core.security import generate_api_key
from models import ApiKey, User


def main() -> None:
    parser = argparse.ArgumentParser(description="Issue the first TalkTwin API key")
    parser.add_argument("email", help="Owner user email")
    parser.add_argument("--name", default="default")
    parser.add_argument("--rate", type=int, default=60)
    parser.add_argument("--concurrent", type=int, default=2)
    args = parser.parse_args()
    email = args.email.lower().strip()
    name = args.name.strip()
    if not name:
        parser.error("name must not be empty")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user:
            print(f"No such user: {email} (create one with scripts/create_admin.py first)")
            return
        if not user.is_active:
            print(f"User is not active: {email}")
            return

        raw, prefix, digest = generate_api_key()
        key = ApiKey(user_id=user.id, name=name, key_prefix=prefix, key_hash=digest,
                     rate_limit_per_min=args.rate, max_concurrent_jobs=args.concurrent,
                     is_active=True)
        db.add(key)
        db.commit()
        db.refresh(key)
        print(f"Key issued: {key.id} (prefix {prefix})")
        print(f"RAW KEY (shown once, store now): {raw}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
