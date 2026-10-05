# auth apis: register, login, logout, change-password, me
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from core.security import create_access_token, hash_password, verify_password
from models import User
from schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeUpdate,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(tags=["user"])


# register api (open signup) -> 201 + user
@router.post("/auth/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED,
             summary="Sign up", description="Create your account. No auth needed. Then login.")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name must not be empty")
    email = str(payload.email).lower().strip()

    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(name=name, email=email, password_hash=hash_password(payload.password), is_active=True)
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    return user


# login api -> returns JWT
@router.post("/auth/login", response_model=TokenResponse,
             summary="Login", description="Email + password -> access_token. Paste it in Authorize (Bearer).")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == str(payload.email).lower().strip()).first()

    if not user or not user.password_hash or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    return TokenResponse(access_token=create_access_token(user.id))


# logout api (stateless JWT -> just tells client to discard)
@router.post("/auth/logout", summary="Logout", description="Stateless JWT — just discard your token.")
def logout():
    return {"message": "Logged out"}


# change password api (auth required)
@router.post("/auth/change-password", summary="Change password", description="Needs login. Old + new password.")
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not current_user.password_hash:
        raise HTTPException(status_code=400, detail="This account has no password set")

    if not verify_password(payload.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Old password is incorrect")

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password changed"}


# me api -> current user info
@router.get("/me", response_model=UserResponse, summary="My profile", description="Who am I? Needs login.")
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


# me api -> update own name
@router.patch("/me", response_model=UserResponse, summary="Rename me", description="Change your own display name.")
def update_me(
    payload: MeUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    clean = payload.name.strip()
    if not clean:
        raise HTTPException(status_code=422, detail="Name must not be empty")
    current_user.name = clean
    db.commit()
    db.refresh(current_user)
    return current_user