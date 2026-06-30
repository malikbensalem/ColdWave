"""3CX Call Control API (v20) client — token auth + click-to-call origination."""
import time
import logging
from urllib.parse import quote
import httpx

logger = logging.getLogger("coldwave.telephony")

# Per-tenant bearer-token cache: { cache_key: {"token": str, "exp": float} }
_token_cache: dict = {}


def _cfg(integ: dict):
    base = (integ.get("tcx_url") or "").rstrip("/")
    return {
        "base_url": base,
        "dn": (integ.get("tcx_extension") or "").strip(),
        "client_id": (integ.get("tcx_username") or "").strip(),
        "client_secret": integ.get("tcx_password") or "",
        "verify": integ.get("tcx_verify_tls", True),
    }


def _require_config(c):
    missing = [k for k in ("base_url", "dn", "client_id", "client_secret") if not c[k]]
    if missing:
        raise ValueError(f"3CX is not fully configured (missing: {', '.join(missing)}).")


async def _get_token(c: dict) -> str:
    key = f"{c['base_url']}|{c['client_id']}"
    cached = _token_cache.get(key)
    now = time.time()
    if cached and cached["exp"] > now + 60:
        return cached["token"]
    async with httpx.AsyncClient(verify=c["verify"], timeout=20.0) as client:
        resp = await client.post(
            f"{c['base_url']}/connect/token",
            data={"client_id": c["client_id"], "client_secret": c["client_secret"],
                  "grant_type": "client_credentials"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"3CX authentication failed ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    token = data["access_token"]
    _token_cache[key] = {"token": token, "exp": now + int(data.get("expires_in", 3600))}
    return token


async def _devices(c: dict, token: str) -> list:
    async with httpx.AsyncClient(verify=c["verify"], timeout=20.0) as client:
        resp = await client.get(f"{c['base_url']}/callcontrol/{c['dn']}/devices",
                                headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        raise RuntimeError(f"Could not list devices for extension {c['dn']} ({resp.status_code}): {resp.text[:200]}")
    return resp.json() or []


async def test_connection(integ: dict) -> dict:
    """Authenticate and list devices for the configured extension."""
    c = _cfg(integ)
    _require_config(c)
    token = await _get_token(c)
    devices = await _devices(c, token)
    return {
        "ok": True,
        "extension": c["dn"],
        "device_count": len(devices),
        "message": (f"Connected to 3CX. Extension {c['dn']} has {len(devices)} registered device(s)."
                    if devices else f"Connected to 3CX, but extension {c['dn']} has no registered devices. "
                                    "Register a phone/softphone on that extension to place calls."),
    }


async def make_call(integ: dict, destination: str) -> dict:
    """Originate a click-to-call: rings the configured extension, then dials the destination."""
    c = _cfg(integ)
    _require_config(c)
    if not destination:
        raise ValueError("No destination number provided.")
    token = await _get_token(c)
    devices = await _devices(c, token)
    if not devices:
        raise RuntimeError(f"Extension {c['dn']} has no registered devices to call from.")
    device_id = devices[0].get("device_id") or devices[0].get("dn")
    path = f"/callcontrol/{c['dn']}/devices/{quote(str(device_id), safe='')}/makecall"
    async with httpx.AsyncClient(verify=c["verify"], timeout=25.0) as client:
        resp = await client.post(f"{c['base_url']}{path}",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                 json={"destination": destination})
    if resp.status_code not in (200, 202):
        raise RuntimeError(f"3CX make-call failed ({resp.status_code}): {resp.text[:200]}")
    body = resp.json() if resp.text else {}
    result = body.get("result", body) if isinstance(body, dict) else {}
    return {
        "ok": True,
        "device_id": device_id,
        "callid": (result.get("callid") if isinstance(result, dict) else None) or body.get("callid"),
        "status": (result.get("status") if isinstance(result, dict) else None) or body.get("status", "Initiated"),
        "raw": body,
    }
