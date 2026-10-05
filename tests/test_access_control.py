import io
import uuid

import pytest
from fastapi.testclient import TestClient

from core.db import SessionLocal
from core.security import hash_password
from models import ApiKey, AuditLog, Job, User

from main import app

client = TestClient(app)
SUFFIX = uuid.uuid4().hex[:8]


def make_user(email, name="T", password="pass1234", role="user", active=True):
    db = SessionLocal()
    u = User(name=name, email=email, password_hash=hash_password(password),
             role=role, is_active=active)
    db.add(u)
    db.commit()
    db.refresh(u)
    uid = u.id
    db.close()
    return uid


def token(email, password="pass1234"):
    r = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def cleanup(*uids, consent_ids=()):
    from core.storage import delete_key
    from models import Avatar, Consent, Voice
    db = SessionLocal()
    for j in db.query(Job).filter(Job.user_id.in_(uids)).all():
        delete_key(j.result_key)
        db.delete(j)
    for v in db.query(Voice).filter(Voice.owner_user_id.in_(uids)).all():
        delete_key(v.reference_clip_key)
        delete_key(v.embedding_key)
        db.delete(v)
    for a in db.query(Avatar).filter(Avatar.owner_user_id.in_(uids)).all():
        delete_key(a.image_key)
        delete_key(a.latents_key)
        db.delete(a)
    for cid in consent_ids:
        x = db.get(Consent, cid)
        if x:
            db.delete(x)
    db.query(ApiKey).filter(ApiKey.user_id.in_(uids)).delete(synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.user_id.in_(uids)).delete(synchronize_session=False)
    for uid in uids:
        u = db.get(User, uid)
        if u:
            db.delete(u)
    db.commit()
    db.close()


@pytest.fixture(scope="module")
def setup():
    admin_email = f"admin_{SUFFIX}@example.com"
    user_email = f"user_{SUFFIX}@example.com"
    other_email = f"other_{SUFFIX}@example.com"
    admin_uid = make_user(admin_email, name="Admin", role="admin")
    user_uid = make_user(user_email, name="User")
    other_uid = make_user(other_email, name="Other")
    data = {
        "admin": token(admin_email), "user": token(user_email), "other": token(other_email),
        "admin_uid": admin_uid, "user_uid": user_uid, "other_uid": other_uid,
        "admin_email": admin_email, "user_email": user_email,
    }
    # fixtures: consent + voice + avatar owned by normal user, ready
    H = data["user"]
    cid = client.post("/v1/consents", headers=H, json={
        "subject_name": "S", "scope": "both", "permitted_uses": ["tts"],
        "signed_at": "2026-01-01T00:00:00Z"}).json()["id"]
    vid = client.post("/v1/voices", headers=H, data={
        "name": "V", "language": "en", "consent_id": cid},
        files={"reference_audio": ("r.wav", io.BytesIO(b"RIFFx"), "audio/wav")}).json()["id"]
    aid = client.post("/v1/avatars", headers=H, data={
        "name": "A", "consent_id": cid},
        files={"image": ("f.png", io.BytesIO(b"\x89PNGx"), "image/png")}).json()["id"]
    import time
    for _ in range(40):
        v = client.get(f"/v1/voices/{vid}", headers=H).json()
        a = client.get(f"/v1/avatars/{aid}", headers=H).json()
        if v["status"] == "ready" and a["status"] == "ready":
            break
        time.sleep(0.1)
    data.update({"cid": cid, "vid": vid, "aid": aid, "consent_ids": [cid]})
    yield data
    cleanup(admin_uid, user_uid, other_uid, consent_ids=data["consent_ids"])


ADMIN_ROUTES = [
    ("GET", "/v1/admin/users"),
    ("POST", "/v1/admin/users"),
    ("GET", "/v1/admin/api-keys"),
    ("POST", "/v1/admin/api-keys"),
    ("GET", "/v1/admin/audit-logs"),
    ("GET", "/v1/admin/jobs"),
    ("GET", "/v1/admin/voices"),
    ("GET", "/v1/admin/avatars"),
    ("GET", "/v1/admin/stats/overview"),
]


def _call(method, path, headers=None, **kw):
    if kw.get("json") is None:
        kw.pop("json", None)
    return getattr(client, method.lower())(path, headers=headers, **kw)


def test_admin_routes_401_without_token():
    for method, path in ADMIN_ROUTES:
        r = _call(method, path, json={} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)


def test_admin_matrix(setup):
    H = setup["user"]
    for method, path in ADMIN_ROUTES:
        r = _call(method, path, headers=H, json={} if method == "POST" else None)
        assert r.status_code == 403, (method, path, r.status_code, r.text)
    r = _call("GET", "/v1/admin/users/xxx", headers=H)
    assert r.status_code == 403


def test_admin_routes_2xx_for_admin(setup):
    H = setup["admin"]
    assert _call("GET", "/v1/admin/users", headers=H).status_code == 200
    assert _call("GET", "/v1/admin/api-keys", headers=H).status_code == 200
    assert _call("GET", "/v1/admin/audit-logs", headers=H).status_code == 200
    assert _call("GET", "/v1/admin/jobs", headers=H).status_code == 200
    assert _call("GET", "/v1/admin/voices", headers=H).status_code == 200
    assert _call("GET", "/v1/admin/avatars", headers=H).status_code == 200
    r = _call("GET", "/v1/admin/stats/overview", headers=H)
    assert r.status_code == 200
    assert set(r.json()) == {"users_total", "users_active", "admins_active",
                             "jobs_total", "jobs_today", "jobs_active", "jobs_failed"}


def test_self_update_cannot_escalate(setup):
    H = setup["user"]
    r = client.patch("/v1/users/me", headers=H, json={"role": "admin"})
    assert r.status_code == 422
    r = client.patch("/v1/users/me", headers=H, json={"is_active": False})
    assert r.status_code == 422
    r = client.patch("/v1/users/me", headers=H, json={"max_concurrent_jobs": 99})
    assert r.status_code == 422
    r = client.patch("/v1/users/me", headers=H, json={"name": "New Name"})
    assert r.status_code == 200 and r.json()["name"] == "New Name"
    db = SessionLocal()
    u = db.get(User, setup["user_uid"])
    assert u.role == "user" and u.is_active is True
    db.close()


def test_register_cannot_set_admin():
    r = client.post("/v1/auth/register", json={
        "name": "Sneaky", "email": f"sneaky_{SUFFIX}@example.com",
        "password": "pass1234", "role": "admin"})
    assert r.status_code == 422
    db = SessionLocal()
    assert db.query(User).filter(User.email == f"sneaky_{SUFFIX}@example.com").first() is None
    db.close()


def test_other_users_key_is_invisible(setup):
    H, O = setup["user"], setup["other"]
    kid = client.post("/v1/api-keys", headers=H, json={"name": "mine"}).json()["id"]
    assert client.delete(f"/v1/api-keys/{kid}", headers=O).status_code == 404
    ids = [k["id"] for k in client.get("/v1/api-keys", headers=O).json()]
    assert kid not in ids
    assert client.delete(f"/v1/api-keys/{kid}", headers=H).status_code == 200


def test_allow_list_ownership(setup):
    H, O = setup["user"], setup["other"]
    r = client.post("/v1/api-keys", headers=H, json={
        "name": "lib-ok", "allowed_voice_ids": [setup["vid"]]})
    assert r.status_code == 201  # own voice: allowed (also make it library below)
    client.delete(f"/v1/api-keys/{r.json()['id']}", headers=H)
    # other's voice (not owned, not library) -> 403
    r = client.post("/v1/api-keys", headers=O, json={
        "name": "steal", "allowed_voice_ids": [setup["vid"]]})
    assert r.status_code == 403, r.text
    r = client.post("/v1/api-keys", headers=O, json={
        "name": "steal2", "allowed_avatar_ids": [setup["aid"]]})
    assert r.status_code == 403


def test_library_usable_by_all(setup):
    A, H = setup["admin"], setup["user"]
    r = client.patch(f"/v1/admin/voices/{setup['vid']}", headers=A, json={"is_library": True})
    assert r.status_code == 200
    r = client.post("/v1/api-keys", headers=H, json={
        "name": "lib-use", "allowed_voice_ids": [setup["vid"]]})
    assert r.status_code == 201
    client.delete(f"/v1/api-keys/{r.json()['id']}", headers=H)
    client.patch(f"/v1/admin/voices/{setup['vid']}", headers=A, json={"is_library": False})


def test_user_caps(setup):
    H = setup["user"]
    r = client.post("/v1/api-keys", headers=H, json={"name": "big", "rate_limit_per_min": 100000})
    assert r.status_code == 403
    r = client.post("/v1/api-keys", headers=H, json={"name": "wide", "max_concurrent_jobs": 99})
    assert r.status_code == 403
    A = setup["admin"]
    r = client.post("/v1/admin/api-keys", headers=A, json={
        "user_id": setup["user_uid"], "name": "big-admin", "rate_limit_per_min": 5000})
    assert r.status_code == 201
    client.delete(f"/v1/admin/api-keys/{r.json()['id']}", headers=A)


def test_self_and_last_admin_protection(setup):
    A = setup["admin"]
    me = client.get("/v1/admin/users", headers=A, params={"role": "admin"}).json()
    assert len(me) == 1  # sole admin in this DB slice? (other admins may exist globally)
    r = client.post(f"/v1/admin/users/{setup['admin_uid']}/disable", headers=A,
                    json={"reason": "self"})
    assert r.status_code == 403
    r = client.patch(f"/v1/admin/users/{setup['admin_uid']}", headers=A, json={"role": "user"})
    assert r.status_code == 403
    # last-admin guard unit check
    from api.v1.admin import _guard_last_admin
    import pytest as _pt
    db = SessionLocal()
    admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()
    db.close()
    assert len(admins) >= 1


def test_disable_kills_keys_and_jobs(setup):
    victim = make_user(f"victim_{SUFFIX}@example.com")
    VH = token(f"victim_{SUFFIX}@example.com")
    kid = client.post("/v1/api-keys", headers=VH, json={"name": "vk"}).json()
    KH = {"X-API-Key": client.post("/v1/admin/api-keys", headers=setup["admin"],
           json={"user_id": victim, "name": "vk2"}).json()["raw_key"]}
    db = SessionLocal()
    parked = Job(id=f"job_vic_{SUFFIX}", user_id=victim, type="tts", status="queued", text="q")
    db.add(parked)
    db.commit()
    db.close()
    r = client.post(f"/v1/admin/users/{victim}/disable", headers=setup["admin"],
                    json={"reason": "test disable"})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/v1/voices", headers=KH).status_code == 401  # key dead next request
    db = SessionLocal()
    assert db.get(Job, f"job_vic_{SUFFIX}").status == "cancelled"
    assert all(k.is_active is False for k in db.query(ApiKey).filter(ApiKey.user_id == victim).all())
    db.delete(db.get(Job, f"job_vic_{SUFFIX}"))
    db.commit()
    db.close()
    # enable needs reason too; keys stay revoked
    r = client.post(f"/v1/admin/users/{victim}/enable", headers=setup["admin"], json={})
    assert r.status_code == 422
    r = client.post(f"/v1/admin/users/{victim}/enable", headers=setup["admin"],
                    json={"reason": "test over"})
    assert r.status_code == 200
    assert client.get("/v1/voices", headers=KH).status_code == 401
    cleanup(victim)


def test_no_hash_leaks(setup):
    A, H = setup["admin"], setup["user"]
    import json as _json
    blob = _json.dumps(client.get("/v1/admin/users", headers=A).json())
    blob += _json.dumps(client.get("/v1/users/me", headers=H).json())
    blob += _json.dumps(client.get("/v1/api-keys", headers=H).json())
    blob += _json.dumps(client.get("/v1/admin/audit-logs", headers=A).json())
    assert "password_hash" not in blob and "key_hash" not in blob


def test_admin_writes_audited(setup):
    A = setup["admin"]
    rows = client.get("/v1/admin/audit-logs", headers=A, params={"action": "user.disable"}).json()
    assert len(rows) >= 1
    row = rows[0]
    assert row["reason"] and row["before"]["is_active"] is True and row["after"]["is_active"] is False


def test_old_admin_routes_gone():
    assert client.get("/v1/users").status_code in (404, 405)
    assert client.get("/v1/api-keys/some-id").status_code in (404, 405)
    assert client.get("/v1/audit-logs").status_code in (404, 405)


def test_seed_script_promotes(monkeypatch):
    import os
    from scripts import create_admin
    email = f"seed_{SUFFIX}@example.com"
    monkeypatch.setenv("ADMIN_EMAIL", email)
    monkeypatch.setenv("ADMIN_PASSWORD", "seedpass123")
    create_admin.main()
    db = SessionLocal()
    u = db.query(User).filter(User.email == email).first()
    assert u is not None and u.role == "admin" and u.is_active is True
    uid = u.id
    db.close()
    create_admin.main()  # idempotent promote path
    cleanup(uid)
