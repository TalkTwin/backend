import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.db import SessionLocal
from core.security import hash_password
from models import User


def main() -> None:
    # First admin lives outside the API: no endpoint can ever grant admin.
    email = os.getenv("ADMIN_EMAIL", "").lower().strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or "@" not in email:
        print("Set ADMIN_EMAIL first")
        return
    if len(password) < 6:
        print("Set ADMIN_PASSWORD first (min 6 chars)")
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.role = "admin"
            user.is_active = True
            db.commit()
            print(f"Promoted to admin: {user.id} ({user.email})")
            return
        user = User(name="Admin", email=email, password_hash=hash_password(password),
                    role="admin", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"Admin created: {user.id} ({user.email})")
    finally:
        db.close()


if __name__ == "__main__":
    main()
