"""Iteration 4 backend tests: owner role, impersonation, admin endpoints,
voice characteristics + elevenlabs models, email integration + campaigns,
KB edit, global AI prompt."""
import os
import time
import pytest
import requests
from datetime import datetime, timezone, timedelta

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
OWNER = {"email": "owner@coldwave.ai", "password": "Owner123!"}
ADMIN = {"email": "admin@coldwave.ai", "password": "Admin123!"}


def _login(creds):
    r = requests.post(f"{BASE_URL}/api/auth/login", json=creds)
    assert r.status_code == 200, f"login failed for {creds['email']}: {r.text}"
    return r.json()


def _hdr(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def owner():
    return _login(OWNER)


@pytest.fixture(scope="module")
def admin():
    return _login(ADMIN)


# ---------- Auth + roles ----------
class TestAuthRoles:
    def test_owner_login_returns_owner_role(self, owner):
        assert owner["role"] == "owner"
        assert owner["access_token"]

    def test_admin_login_returns_admin_role(self, admin):
        assert admin["role"] == "admin"
        assert admin["access_token"]


# ---------- Admin / owner endpoints ----------
class TestAdminEndpoints:
    def test_businesses_owner_ok(self, owner):
        r = requests.get(f"{BASE_URL}/api/admin/businesses", headers=_hdr(owner["access_token"]))
        assert r.status_code == 200
        biz = r.json()
        assert isinstance(biz, list) and len(biz) >= 1
        sample = biz[0]
        for k in ("id", "name", "users", "contacts", "campaigns", "calls"):
            assert k in sample

    def test_businesses_admin_forbidden(self, admin):
        r = requests.get(f"{BASE_URL}/api/admin/businesses", headers=_hdr(admin["access_token"]))
        assert r.status_code == 403

    def test_users_owner_returns_org_name(self, owner):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=_hdr(owner["access_token"]))
        assert r.status_code == 200
        users = r.json()
        assert any(u.get("org_name") for u in users), "expected org_name on users"
        assert any(u["email"] == OWNER["email"] for u in users)

    def test_users_admin_forbidden(self, admin):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=_hdr(admin["access_token"]))
        assert r.status_code == 403

    def test_global_settings_persist(self, owner):
        prompt = "TEST_GLOBAL Be concise. Always say hi."
        r = requests.put(f"{BASE_URL}/api/admin/global-settings",
                         headers=_hdr(owner["access_token"]),
                         json={"ai_system_prompt": prompt})
        assert r.status_code == 200
        assert r.json()["ai_system_prompt"] == prompt
        r2 = requests.get(f"{BASE_URL}/api/admin/global-settings", headers=_hdr(owner["access_token"]))
        assert r2.status_code == 200
        assert r2.json()["ai_system_prompt"] == prompt
        # cleanup
        requests.put(f"{BASE_URL}/api/admin/global-settings",
                     headers=_hdr(owner["access_token"]),
                     json={"ai_system_prompt": ""})

    def test_global_settings_admin_forbidden(self, admin):
        r = requests.get(f"{BASE_URL}/api/admin/global-settings", headers=_hdr(admin["access_token"]))
        assert r.status_code == 403
        r2 = requests.put(f"{BASE_URL}/api/admin/global-settings",
                          headers=_hdr(admin["access_token"]),
                          json={"ai_system_prompt": "x"})
        assert r2.status_code == 403


# ---------- Impersonation ----------
class TestImpersonation:
    def test_owner_can_impersonate_admin_and_stop(self, owner, admin):
        target_id = admin["id"]
        r = requests.post(f"{BASE_URL}/api/auth/impersonate",
                          headers=_hdr(owner["access_token"]),
                          json={"user_id": target_id})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["impersonating"] is True
        assert body["impersonator"]["email"] == OWNER["email"]
        assert body["email"] == ADMIN["email"]
        imp_tok = body["access_token"]

        me = requests.get(f"{BASE_URL}/api/auth/me", headers=_hdr(imp_tok))
        assert me.status_code == 200
        me_body = me.json()
        assert me_body["email"] == ADMIN["email"]
        assert me_body["impersonating"] is True

        stop = requests.post(f"{BASE_URL}/api/auth/stop-impersonation",
                             headers=_hdr(imp_tok))
        assert stop.status_code == 200
        back = stop.json()
        assert back["email"] == OWNER["email"]
        assert back["role"] == "owner"
        assert back.get("impersonating") in (False, None)

    def test_admin_cannot_impersonate_user_in_other_org(self, admin, owner):
        # Find a user in a different org than admin
        users_resp = requests.get(f"{BASE_URL}/api/admin/users", headers=_hdr(owner["access_token"]))
        users = users_resp.json()
        admin_org = admin["org_id"]
        other = next((u for u in users if u["org_id"] != admin_org and u["role"] != "owner"), None)
        if not other:
            # create a new org+user via register
            uniq = f"test_other_{int(time.time())}@coldwave.ai"
            reg = requests.post(f"{BASE_URL}/api/auth/register", json={
                "email": uniq, "password": "Pass1234!", "name": "Test Other", "org_name": f"TEST_Other_{int(time.time())}"
            })
            assert reg.status_code == 200, reg.text
            other = reg.json()
        r = requests.post(f"{BASE_URL}/api/auth/impersonate",
                          headers=_hdr(admin["access_token"]),
                          json={"user_id": other["id"]})
        assert r.status_code == 403

    def test_admin_can_impersonate_user_within_own_org(self, admin):
        # Create a colleague within admin's org via invite
        uniq = f"colleague_{int(time.time())}@coldwave.ai"
        inv = requests.post(f"{BASE_URL}/api/users",
                            headers=_hdr(admin["access_token"]),
                            json={"email": uniq, "name": "Colleague", "password": "Pass1234!", "role": "agent"})
        assert inv.status_code == 200, inv.text
        colleague = inv.json()
        r = requests.post(f"{BASE_URL}/api/auth/impersonate",
                          headers=_hdr(admin["access_token"]),
                          json={"user_id": colleague["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["email"] == uniq
        # cleanup
        requests.delete(f"{BASE_URL}/api/users/{colleague['id']}",
                        headers=_hdr(admin["access_token"]))


# ---------- Voices ----------
class TestVoices:
    def test_elevenlabs_models(self, admin):
        r = requests.get(f"{BASE_URL}/api/elevenlabs/models", headers=_hdr(admin["access_token"]))
        assert r.status_code == 200
        models = r.json().get("models", [])
        assert isinstance(models, list) and len(models) >= 1

    def test_voice_characteristics_update_and_persist(self, admin):
        payload = {"name": "TEST_George", "persona": "TEST_persona_calm"}
        r = requests.put(f"{BASE_URL}/api/voices/george/characteristics",
                         headers=_hdr(admin["access_token"]), json=payload)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["name"] == "TEST_George"
        # GET /api/voices reflects override
        v = requests.get(f"{BASE_URL}/api/voices", headers=_hdr(admin["access_token"]))
        assert v.status_code == 200
        body = v.json()
        assert "elevenlabs_enabled" in body
        george = next((x for x in body["voices"] if x["id"] == "george"), None)
        assert george is not None
        assert george["display_name"] == "TEST_George"
        assert george["persona"] == "TEST_persona_calm"
        assert george["customized"] is True
        # cleanup -- reset
        requests.put(f"{BASE_URL}/api/voices/george/characteristics",
                     headers=_hdr(admin["access_token"]),
                     json={"name": "George", "persona": ""})


# ---------- Email integration + campaigns ----------
class TestEmail:
    def test_full_email_flow(self, admin):
        tok = admin["access_token"]
        # connect
        r = requests.put(f"{BASE_URL}/api/email/integration",
                         headers=_hdr(tok),
                         json={"provider": "gmail", "account_email": "ops@coldwave.ai"})
        assert r.status_code == 200
        assert r.json()["connected"] is True
        # get integration
        g = requests.get(f"{BASE_URL}/api/email/integration", headers=_hdr(tok))
        assert g.status_code == 200 and g.json()["connected"] is True
        # recipients
        rec = requests.get(f"{BASE_URL}/api/email/recipients?audience=all", headers=_hdr(tok))
        assert rec.status_code == 200
        assert "count" in rec.json()
        # send now
        c1 = requests.post(f"{BASE_URL}/api/email-campaigns",
                           headers=_hdr(tok),
                           json={"name": "TEST_now", "subject": "hi", "body": "hello",
                                 "schedule_type": "now", "audience": "all"})
        assert c1.status_code == 200, c1.text
        b1 = c1.json()
        assert b1["status"] == "sent"
        assert "sent_count" in b1
        # scheduled
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        c2 = requests.post(f"{BASE_URL}/api/email-campaigns",
                           headers=_hdr(tok),
                           json={"name": "TEST_scheduled", "subject": "hi", "body": "hello",
                                 "schedule_type": "scheduled", "audience": "all",
                                 "scheduled_at": future})
        assert c2.status_code == 200, c2.text
        b2 = c2.json()
        assert b2["status"] == "scheduled"
        assert b2.get("scheduled_at")
        # send-now action
        s = requests.post(f"{BASE_URL}/api/email-campaigns/{b2['id']}/send-now",
                          headers=_hdr(tok))
        assert s.status_code == 200
        assert s.json().get("mock") is True
        # delete both
        d1 = requests.delete(f"{BASE_URL}/api/email-campaigns/{b1['id']}", headers=_hdr(tok))
        d2 = requests.delete(f"{BASE_URL}/api/email-campaigns/{b2['id']}", headers=_hdr(tok))
        assert d1.status_code == 200 and d2.status_code == 200


# ---------- KB edit ----------
class TestKBEdit:
    def test_create_then_edit(self, admin):
        tok = admin["access_token"]
        c = requests.post(f"{BASE_URL}/api/kb",
                          headers=_hdr(tok),
                          json={"title": "TEST_KB_Original", "content": "Original body"})
        assert c.status_code == 200, c.text
        kb_id = c.json()["id"]
        u = requests.put(f"{BASE_URL}/api/kb/{kb_id}",
                         headers=_hdr(tok),
                         json={"title": "TEST_KB_Updated", "content": "Updated body"})
        assert u.status_code == 200, u.text
        updated = u.json()
        assert updated["title"] == "TEST_KB_Updated"
        assert updated["content"] == "Updated body"
        # cleanup
        requests.delete(f"{BASE_URL}/api/kb/{kb_id}", headers=_hdr(tok))
