"""3CX Call Control API (v20) client — token auth + click-to-call origination."""
import time
import hashlib
import logging
from urllib.parse import quote
import httpx

logger = logging.getLogger("coldwave.telephony")

# Per-tenant bearer-token cache: { cache_key: {"token": str, "exp": float} }
_token_cache: dict = {}


def _cfg(integ: dict):
    base = (integ.get("tcx_url") or "").strip().rstrip("/")
    if base and not base.lower().startswith(("http://", "https://")):
        base = "https://" + base
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
    secret_sig = hashlib.sha256((c["client_secret"] or "").encode()).hexdigest()[:12]
    key = f"{c['base_url']}|{c['client_id']}|{secret_sig}"
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


async def _list_dns(c: dict, token: str) -> list:
    async with httpx.AsyncClient(verify=c["verify"], timeout=20.0) as client:
        resp = await client.get(f"{c['base_url']}/callcontrol",
                                headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        raise RuntimeError(f"Could not list controllable DNs ({resp.status_code}): {resp.text[:200]}")
    return resp.json() or []


async def test_connection(integ: dict) -> dict:
    """Authenticate and confirm the configured DN is controllable by this API app."""
    c = _cfg(integ)
    _require_config(c)
    token = await _get_token(c)
    dns = await _list_dns(c, token)
    match = next((d for d in dns if isinstance(d, dict) and str(d.get("dn")) == c["dn"]), None)
    if not match:
        available = ", ".join(str(d.get("dn")) for d in dns if isinstance(d, dict)) or "none"
        raise RuntimeError(f"Authenticated, but DN {c['dn']} is not controllable by this API app. "
                           f"Controllable DNs: {available}. For automated outbound use a Route Point DN.")
    dn_type = match.get("type", "")
    is_rp = "routepoint" in str(dn_type).lower()
    devices = match.get("devices") or []
    return {
        "ok": True,
        "extension": c["dn"],
        "dn_type": dn_type,
        "is_route_point": is_rp,
        "device_count": len(devices),
        "message": (f"Connected to 3CX. DN {c['dn']} is a Route Point — ready for direct automated outbound calls."
                    if is_rp else
                    f"Connected to 3CX. DN {c['dn']} is a user extension with {len(devices)} device(s). "
                    f"Note: calling from a user extension rings that extension — use a Route Point for automated outbound."),
    }


def _parse_makecall(resp) -> dict:
    body = resp.json() if resp.text else {}
    result = body.get("result", body) if isinstance(body, dict) else {}
    return {
        "ok": True,
        "callid": (result.get("callid") if isinstance(result, dict) else None) or (body.get("callid") if isinstance(body, dict) else None),
        "status": (result.get("status") if isinstance(result, dict) else None) or (body.get("status") if isinstance(body, dict) else None) or "Initiated",
        "raw": body,
    }


async def make_call(integ: dict, destination: str) -> dict:
    """Originate a direct outbound call to `destination`.

    Primary path is a DN-level makecall (Route Point style) which dials the
    destination DIRECTLY with no human leg — the correct mode for automated /
    AI outbound. Falls back to a device makecall only if the DN has registered
    devices (i.e. it's a normal extension).
    """
    c = _cfg(integ)
    _require_config(c)
    if not destination:
        raise ValueError("No destination number provided.")
    destination = destination.strip().replace(" ", "")
    token = await _get_token(c)
    payload = {"destination": destination, "timeout": 30}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(verify=c["verify"], timeout=25.0) as client:
        # 1) DN-level direct dial (Route Point) — dials the client directly.
        resp = await client.post(f"{c['base_url']}/callcontrol/{c['dn']}/makecall",
                                 headers=headers, json=payload)
        if resp.status_code in (200, 202):
            return _parse_makecall(resp)
        dn_err = f"{resp.status_code}: {resp.text[:160]}"

        # 2) Fallback: device-level makecall (normal extension with a softphone).
        dresp = await client.get(f"{c['base_url']}/callcontrol/{c['dn']}/devices",
                                 headers={"Authorization": f"Bearer {token}"})
        devices = dresp.json() if dresp.status_code == 200 and dresp.text else []
        if devices:
            device_id = devices[0].get("device_id") or devices[0].get("dn")
            path = f"/callcontrol/{c['dn']}/devices/{quote(str(device_id), safe='')}/makecall"
            resp2 = await client.post(f"{c['base_url']}{path}", headers=headers, json=payload)
            if resp2.status_code in (200, 202):
                return _parse_makecall(resp2)
            raise RuntimeError(f"3CX make-call failed (device {resp2.status_code}): {resp2.text[:160]}")

    raise RuntimeError(
        f"3CX could not place a direct outbound call (DN {c['dn']} returned {dn_err}). "
        "For automated outbound with no human leg, set 'Extension / DN' to a 3CX Route Point "
        "assigned to this API app — a normal user extension will ring itself instead of dialing out."
    )


async def twilio_make_call(integ: dict, destination: str, say_text: str = None,
                           voice_url: str = None, status_url: str = None, amd_url: str = None) -> dict:
    """Originate a real outbound call via Twilio Programmable Voice.
    If `voice_url` is given, Twilio fetches TwiML from that webhook (runs the turn-based AI
    conversation in the campaign voice). Otherwise it speaks `say_text` via inline TwiML."""
    from xml.sax.saxutils import escape
    sid = (integ.get("twilio_account_sid") or "").strip()
    token = (integ.get("twilio_auth_token") or "").strip()
    from_num = (integ.get("twilio_phone_number") or "").strip()
    if not (sid and token and from_num):
        raise ValueError("Twilio is not fully configured — set Account SID, Auth Token and a Twilio phone number in Settings → Integrations.")
    if not destination:
        raise ValueError("No destination number provided.")
    dest = destination.strip().replace(" ", "")
    data = {"To": dest, "From": from_num}
    if voice_url:
        data["Url"] = voice_url
        data["Method"] = "POST"
        if status_url:
            data["StatusCallback"] = status_url
            data["StatusCallbackEvent"] = "completed"
            data["StatusCallbackMethod"] = "POST"
        if amd_url:
            # Async Answering Machine Detection: connects humans immediately (no added latency);
            # Twilio posts the result (AnsweredBy) to amd_url so we can end voicemail calls + tag them.
            data["MachineDetection"] = "Enable"
            data["AsyncAmd"] = "true"
            data["AsyncAmdStatusCallback"] = amd_url
            data["AsyncAmdStatusCallbackMethod"] = "POST"
    else:
        say = say_text or "Hello, this is an automated call from your A I assistant. Please hold a moment."
        data["Twiml"] = f'<Response><Say voice="Polly.Amy">{escape(say)}</Say><Pause length="3"/></Response>'
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.post(url, data=data, auth=(sid, token))
    if r.status_code in (200, 201):
        d = r.json()
        return {"callid": d.get("sid"), "status": d.get("status", "queued")}
    if r.status_code in (401, 403):
        raise RuntimeError("Twilio rejected the credentials (401/403). Re-check your Account SID / Auth Token.")
    raise RuntimeError(f"Twilio call failed ({r.status_code}): {r.text[:180]}")


async def twilio_update_call(integ: dict, call_sid: str, twiml: str) -> dict:
    """Redirect an in-progress Twilio call to new TwiML (used for human takeover / hangup)."""
    sid = (integ.get("twilio_account_sid") or "").strip()
    token = (integ.get("twilio_auth_token") or "").strip()
    if not (sid and token):
        raise ValueError("Twilio is not configured.")
    if not call_sid:
        raise ValueError("No Twilio call SID for this call.")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls/{call_sid}.json"
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.post(url, data={"Twiml": twiml}, auth=(sid, token))
    if r.status_code in (200, 201):
        d = r.json()
        return {"callid": d.get("sid"), "status": d.get("status", "in-progress")}
    if r.status_code in (401, 403):
        raise RuntimeError("Twilio rejected the credentials (401/403).")
    raise RuntimeError(f"Twilio update failed ({r.status_code}): {r.text[:180]}")


async def twilio_hangup_call(integ: dict, call_sid: str) -> dict:
    """End an in-progress Twilio call."""
    sid = (integ.get("twilio_account_sid") or "").strip()
    token = (integ.get("twilio_auth_token") or "").strip()
    if not (sid and token and call_sid):
        raise ValueError("Twilio is not configured or no call SID.")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls/{call_sid}.json"
    async with httpx.AsyncClient(timeout=25.0) as client:
        r = await client.post(url, data={"Status": "completed"}, auth=(sid, token))
    if r.status_code in (200, 201):
        return {"status": "completed"}
    raise RuntimeError(f"Twilio hangup failed ({r.status_code}): {r.text[:180]}")
