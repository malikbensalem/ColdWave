"""Iteration 5 RBAC/Impersonation/Blueprints/Ban — backend tests."""
import os
import uuid
import pytest
import requests

BASE = os.environ.get("REACT_APP_BACKEND_URL", "https://dialflow-crm-1.preview.emergentagent.com").rstrip("/")
OWNER = {"email": "owner@coldwave.ai", "password": "Owner123!"}
ADMIN = {"email": "admin@coldwave.ai", "password": "Admin123!"}


def _login(creds):
    r = requests.post(f"{BASE}/api/auth/login", json=creds)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()


@pytest.fixture(scope="session")
def owner_session():
    data = _login(OWNER)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    s.user = data
    return s


@pytest.fixture(scope="session")
def admin_session():
    data = _login(ADMIN)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {data['access_token']}"})
    s.user = data
    return s


# -------- /api/systems & /api/auth/me capabilities --------
class TestSystemsAndMe:
    def test_systems_endpoint(self, owner_session):
        r = owner_session.get(f"{BASE}/api/systems")
        assert r.status_code == 200
        d = r.json()
        assert "systems" in d and "capabilities" in d
        assert "platform_admin" in d["systems"]
        assert "blueprints" in d["systems"]
        assert "view_all_businesses" in d["capabilities"]

    def test_owner_me_perms(self, owner_session):
        r = owner_session.get(f"{BASE}/api/auth/me")
        assert r.status_code == 200
        d = r.json()
        assert d["role"] == "owner"
        assert d["permissions"]["platform_admin"]["read"] is True
        assert "view_all_businesses" in d["capabilities"]
        assert "impersonate_any_business" in d["capabilities"]

    def test_admin_me_perms(self, admin_session):
        r = admin_session.get(f"{BASE}/api/auth/me")
        assert r.status_code == 200
        d = r.json()
        assert d["role"] == "admin"
        assert d["permissions"]["platform_admin"]["read"] is False
        caps = d["capabilities"]
        assert "grant_privileges" in caps
        assert "impersonate_users" in caps
        assert "ban_users" in caps
        assert "view_all_businesses" not in caps


# -------- Roles CRUD --------
class TestRoles:
    def test_list_roles_owner_sees_owner_builtin(self, owner_session):
        r = owner_session.get(f"{BASE}/api/roles")
        assert r.status_code == 200
        names = [x["name"] for x in r.json()]
        assert "owner" in names and "admin" in names and "agent" in names

    def test_list_roles_admin_no_owner(self, admin_session):
        r = admin_session.get(f"{BASE}/api/roles")
        assert r.status_code == 200
        names = [x["name"] for x in r.json()]
        assert "owner" not in names
        assert "admin" in names and "agent" in names

    def test_admin_create_role_and_capability_filter(self, admin_session):
        nm = f"TEST_role_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": nm,
            "permissions": {"leads": {"create": True, "read": True, "update": True, "delete": False}},
            "capabilities": ["ban_users", "view_all_businesses"],  # second one should be filtered
        }
        r = admin_session.post(f"{BASE}/api/roles", json=payload)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["name"] == nm.lower()
        assert "ban_users" in d["capabilities"]
        # admin doesn't hold view_all_businesses -> should be filtered
        assert "view_all_businesses" not in d["capabilities"]
        assert d["permissions"]["leads"]["create"] is True
        assert d["permissions"]["dashboard"]["read"] is False  # normalised

        # Update
        r = admin_session.put(
            f"{BASE}/api/roles/{d['id']}",
            json={"permissions": {"leads": {"create": False, "read": True, "update": False, "delete": False}}},
        )
        assert r.status_code == 200
        assert r.json()["permissions"]["leads"]["create"] is False

        # Delete unused role
        r = admin_session.delete(f"{BASE}/api/roles/{d['id']}")
        assert r.status_code == 200

    def test_delete_role_assigned_returns_400(self, admin_session):
        nm = f"TEST_inuse_{uuid.uuid4().hex[:6]}"
        r = admin_session.post(f"{BASE}/api/roles", json={"name": nm, "permissions": {}, "capabilities": []})
        assert r.status_code == 200
        rid = r.json()["id"]
        # create user with that role
        email = f"test_userrole_{uuid.uuid4().hex[:6]}@x.com"
        r2 = admin_session.post(f"{BASE}/api/users",
                                json={"email": email, "name": "tu", "password": "Pass1234!", "role": nm.lower()})
        assert r2.status_code in (200, 201), r2.text
        uid = r2.json()["id"]
        # delete should fail
        r3 = admin_session.delete(f"{BASE}/api/roles/{rid}")
        assert r3.status_code == 400
        # cleanup
        admin_session.delete(f"{BASE}/api/users/{uid}")
        admin_session.delete(f"{BASE}/api/roles/{rid}")

    def test_reserved_role_name(self, admin_session):
        r = admin_session.post(f"{BASE}/api/roles", json={"name": "admin", "permissions": {}, "capabilities": []})
        assert r.status_code == 400


# -------- Ban / Unban --------
class TestBan:
    def test_ban_blocks_login_and_unban_restores(self, admin_session):
        email = f"test_ban_{uuid.uuid4().hex[:6]}@x.com"
        pw = "Pass1234!"
        r = admin_session.post(f"{BASE}/api/users",
                               json={"email": email, "name": "BT", "password": pw, "role": "agent"})
        assert r.status_code in (200, 201), r.text
        uid = r.json()["id"]
        # verify login works
        assert requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}).status_code == 200
        # ban
        r = admin_session.post(f"{BASE}/api/users/{uid}/ban", json={"reason": "Spamming"})
        assert r.status_code == 200, r.text
        # login should be 403 with reason
        r2 = requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw})
        assert r2.status_code == 403
        assert "Spamming" in r2.text or "banned" in r2.text.lower()
        # unban
        r = admin_session.post(f"{BASE}/api/users/{uid}/unban")
        assert r.status_code == 200
        assert requests.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}).status_code == 200
        admin_session.delete(f"{BASE}/api/users/{uid}")

    def test_cannot_ban_self_or_owner(self, admin_session, owner_session):
        my_id = admin_session.user["id"]
        r = admin_session.post(f"{BASE}/api/users/{my_id}/ban", json={"reason": "x"})
        assert r.status_code in (400, 403)
        owner_id = owner_session.user["id"]
        r = admin_session.post(f"{BASE}/api/users/{owner_id}/ban", json={"reason": "x"})
        # admin can't even see owner cross-org; expect 4xx
        assert r.status_code in (400, 403, 404)


# -------- Impersonation --------
class TestImpersonation:
    def test_owner_impersonate_admin_cross_org(self, owner_session):
        r = owner_session.post(f"{BASE}/api/auth/impersonate", json={"user_id": "user_invalid"})
        assert r.status_code in (404, 400)
        # find admin user via /api/admin/users
        users = owner_session.get(f"{BASE}/api/admin/users").json()
        admin_user = next(u for u in users if u["email"] == ADMIN["email"])
        r = requests.post(f"{BASE}/api/auth/impersonate",
                          headers={"Authorization": f"Bearer {owner_session.user['access_token']}"},
                          json={"user_id": admin_user["id"]})
        assert r.status_code == 200, r.text
        tok = r.json()["access_token"]
        # /admin/businesses should be 403 while impersonating
        r2 = requests.get(f"{BASE}/api/admin/businesses", headers={"Authorization": f"Bearer {tok}"})
        assert r2.status_code == 403
        # stop
        r3 = requests.post(f"{BASE}/api/auth/stop-impersonation", headers={"Authorization": f"Bearer {tok}"})
        assert r3.status_code == 200
        assert r3.json()["role"] == "owner"

    def test_admin_cannot_impersonate_cross_org(self, owner_session, admin_session):
        # find a user in another org (the owner's own org platform user)
        users = owner_session.get(f"{BASE}/api/admin/users").json()
        cross = next((u for u in users if u["org_id"] != admin_session.user["org_id"] and u["role"] != "owner"), None)
        if not cross:
            pytest.skip("no cross-org user available")
        r = admin_session.post(f"{BASE}/api/auth/impersonate", json={"user_id": cross["id"]})
        assert r.status_code == 403

    def test_cannot_impersonate_owner(self, owner_session, admin_session):
        users = owner_session.get(f"{BASE}/api/admin/users").json()
        owner_u = next(u for u in users if u["role"] == "owner")
        r = admin_session.post(f"{BASE}/api/auth/impersonate", json={"user_id": owner_u["id"]})
        assert r.status_code == 403

    def test_role_preview(self, owner_session):
        r = requests.post(f"{BASE}/api/auth/impersonate",
                          headers={"Authorization": f"Bearer {owner_session.user['access_token']}"},
                          json={"role": "agent", "org_id": owner_session.user["org_id"]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["preview_role"] is True
        assert d["role"] == "agent"
        assert d["permissions"]["platform_admin"]["read"] is False
        assert d["permissions"]["integrations"]["read"] is False
        # admin endpoint blocked
        r2 = requests.get(f"{BASE}/api/admin/businesses", headers={"Authorization": f"Bearer {d['access_token']}"})
        assert r2.status_code == 403

    def test_owner_role_preview_disallowed(self, owner_session):
        r = owner_session.post(f"{BASE}/api/auth/impersonate", json={"role": "owner", "org_id": owner_session.user["org_id"]})
        assert r.status_code == 403

    def test_banned_user_cannot_be_impersonated(self, admin_session, owner_session):
        email = f"test_banimp_{uuid.uuid4().hex[:6]}@x.com"
        r = admin_session.post(f"{BASE}/api/users",
                               json={"email": email, "name": "B", "password": "Pass1234!", "role": "agent"})
        uid = r.json()["id"]
        admin_session.post(f"{BASE}/api/users/{uid}/ban", json={"reason": "test"})
        r2 = owner_session.post(f"{BASE}/api/auth/impersonate", json={"user_id": uid})
        assert r2.status_code == 400
        admin_session.post(f"{BASE}/api/users/{uid}/unban")
        admin_session.delete(f"{BASE}/api/users/{uid}")


# -------- Blueprints --------
class TestBlueprints:
    def test_non_owner_blocked(self, admin_session):
        assert admin_session.get(f"{BASE}/api/admin/blueprints").status_code == 403
        assert admin_session.get(f"{BASE}/api/admin/businesses").status_code == 403

    def test_blueprint_crud_and_default(self, owner_session):
        r = owner_session.post(f"{BASE}/api/admin/blueprints",
                               json={"name": "TEST_BP", "prompt": "p", "is_default": False})
        assert r.status_code == 200, r.text
        bp = r.json()
        bid = bp["id"]

        r = owner_session.put(f"{BASE}/api/admin/blueprints/{bid}",
                              json={"name": "TEST_BP2", "prompt": "p2", "is_default": True})
        assert r.status_code == 200
        assert r.json()["is_default"] is True

        # create another and make default
        r = owner_session.post(f"{BASE}/api/admin/blueprints",
                               json={"name": "TEST_BP_B", "prompt": "p", "is_default": True})
        bid2 = r.json()["id"]
        # original should no longer be default
        all_bps = owner_session.get(f"{BASE}/api/admin/blueprints").json()
        b1 = next(b for b in all_bps if b["id"] == bid)
        assert b1["is_default"] is False

        # cannot delete current default
        r = owner_session.delete(f"{BASE}/api/admin/blueprints/{bid2}")
        assert r.status_code == 400

        # Set bid as default again, delete bid2
        owner_session.put(f"{BASE}/api/admin/blueprints/{bid}", json={"is_default": True})
        assert owner_session.delete(f"{BASE}/api/admin/blueprints/{bid2}").status_code == 200

        # cleanup: ensure default set back to bp_default
        bps = owner_session.get(f"{BASE}/api/admin/blueprints").json()
        seed = next((b for b in bps if b["id"] == "bp_default"), None)
        if seed:
            owner_session.put(f"{BASE}/api/admin/blueprints/bp_default", json={"is_default": True})
        owner_session.delete(f"{BASE}/api/admin/blueprints/{bid}")

    def test_assign_blueprint_to_business(self, owner_session):
        orgs = owner_session.get(f"{BASE}/api/admin/businesses").json()
        admin_org = next(o for o in orgs if o["name"] == "ColdWave Demo Co")
        bps = owner_session.get(f"{BASE}/api/admin/blueprints").json()
        any_bp = bps[0]
        r = owner_session.put(f"{BASE}/api/admin/businesses/{admin_org['id']}/blueprint",
                              json={"blueprint_id": any_bp["id"]})
        assert r.status_code == 200
        # verify
        orgs2 = owner_session.get(f"{BASE}/api/admin/businesses").json()
        a2 = next(o for o in orgs2 if o["id"] == admin_org["id"])
        assert a2["blueprint_id"] == any_bp["id"]
        # clear
        r = owner_session.put(f"{BASE}/api/admin/businesses/{admin_org['id']}/blueprint",
                              json={"blueprint_id": None})
        assert r.status_code == 200


# -------- Filters --------
class TestFilters:
    def test_business_search_filter(self, owner_session):
        r = owner_session.get(f"{BASE}/api/admin/businesses?search=ColdWave")
        assert r.status_code == 200
        names = [o["name"] for o in r.json()]
        assert any("ColdWave" in n for n in names)

    def test_users_filters(self, owner_session):
        r = owner_session.get(f"{BASE}/api/admin/users?role=owner")
        assert r.status_code == 200
        assert all(u["role"] == "owner" for u in r.json())

        r = owner_session.get(f"{BASE}/api/admin/users?search=admin@coldwave")
        assert r.status_code == 200
        emails = [u["email"] for u in r.json()]
        assert "admin@coldwave.ai" in emails
