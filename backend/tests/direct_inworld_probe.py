"""Direct probe of generate_tts_telephony for the Inworld voice-id fallback fix (iteration 18)."""
import asyncio
import os
import sys
import time

sys.path.insert(0, "/app/backend")


async def main():
    from database import db
    from integrations import generate_tts_telephony, select_tts_provider

    org = await db.organizations.find_one({"name": {"$regex": "Demo"}}, {"_id": 0})
    if not org:
        org = await db.organizations.find_one({}, {"_id": 0})
    integ = org.get("integrations", {})
    print("ORG:", org.get("name"), org.get("id"))
    print("tts_stt_provider =", integ.get("tts_stt_provider"))
    print("inworld key set =", bool((integ.get("inworld_api_key") or "").strip()))
    print("inworld_tts_voice_id =", integ.get("inworld_tts_voice_id"))
    print("select_tts_provider =", select_tts_provider(org))

    for vid in ["george", "charlie", "Ashley", "definitely_not_a_voice_xyz"]:
        t0 = time.time()
        r = await generate_tts_telephony(org, f"Hello, this is a probe for {vid}.", voice_id=vid, use_cache=False)
        dt = time.time() - t0
        print(f"voice_id={vid!r:32} -> provider={r.get('provider')} "
              f"audio_len={len(r.get('audio_b64') or '')} err={r.get('error')!r} t={dt:.2f}s")

    # campaigns' stored voice ids
    camps = await db.campaigns.find({"org_id": org["id"]}, {"_id": 0, "name": 1, "voice_id": 1}).to_list(50)
    print("CAMPAIGNS:", [(c.get("name"), c.get("voice_id")) for c in camps])


asyncio.run(main())
