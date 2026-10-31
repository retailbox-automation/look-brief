"""Look Brief web app (FastAPI). Replay by default; Live only with a server-side key and a unit budget."""

from __future__ import annotations

import json
import re
import shutil
import threading
import time
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import __version__, attest, build_id, photo_check, pipeline
from . import recipe as rcp
from .config import Settings, youcam_key
from .engine import LiveEngine, NotRecorded, ReplayEngine, SessionCtx
from .photo_check import hint_for
from .store import REVIEW_STATUSES, Store
from .youcam import UNITS, YouCamClient, YouCamError

HERE = Path(__file__).resolve().parent
SAFE_NAME = re.compile(r"^[a-z0-9_.-]+\.(jpg|png)$")
REVIEW_LABELS = {"do": "I'll do this", "swap": "I'll swap the product", "discuss": "Let's discuss"}
LOOK_UNITS = UNITS["mu-transfer"] + UNITS["hair-transfer"] + UNITS["makeup-vto"]


class EditIn(BaseModel):
    zone: str | None = None
    op: str | None = None
    action: str = "add"  # add | undo | reset


class BriefIn(BaseModel):
    t: str


class ReviewIn(BaseModel):
    t: str
    zone: str
    status: str
    note: str = ""


def iso(t: float | None) -> str | None:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t)) if t else None


def load_samples(d: Path) -> dict[str, dict]:
    out = {}
    for sd in sorted(p for p in d.glob("*") if (p / "sample.json").exists()):
        meta = json.loads((sd / "sample.json").read_text())
        meta["recorded"] = (sd / "manifest.json").exists()
        meta["dir"] = sd
        out[meta["id"]] = meta
    return out


class CreditCache:
    def __init__(self, client_factory, ttl: float = 60.0):
        self._factory = client_factory
        self._ttl = ttl
        self._value: int | None = None
        self._at = 0.0
        self._lock = threading.Lock()

    def get(self) -> int | None:
        with self._lock:
            if time.time() - self._at < self._ttl:
                return self._value
            client = self._factory()
            if client is None:
                return None
            try:
                self._value = client.credit()
            except YouCamError:
                self._value = None
            self._at = time.time()
            return self._value


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(s.data_dir / "lookbrief.db")
    signer = attest.load_signer(s.attest_key_b64, s.data_dir / "attest_ed25519.key", ephemeral=s.attest_ephemeral)
    samples = load_samples(s.samples_dir)
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app = FastAPI(title="Look Brief", version=__version__, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    key = youcam_key()
    client_holder: dict[str, YouCamClient] = {}

    def live_client() -> YouCamClient | None:
        if not key:
            return None
        if "c" not in client_holder:
            client_holder["c"] = YouCamClient(key, call_log=s.data_dir / "youcam-calls.jsonl")
        return client_holder["c"]

    credit = CreditCache(live_client)

    def session_dir(sid: str) -> Path:
        return s.data_dir / "sessions" / sid

    def client_ip(request: Request) -> str:
        if s.trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def live_status(ip: str, need_units: int = LOOK_UNITS) -> dict:
        spent = store.live_units_spent()
        st = {
            "live_enabled": s.live_enabled and bool(key),
            "budget_total": s.live_unit_budget,
            "budget_spent": spent,
            "budget_left": max(s.live_unit_budget - spent, 0),
            "ip_sessions_today": store.ip_sessions_today(ip),
            "ip_sessions_limit": s.live_sessions_per_ip_day,
            "session_unit_cap": s.live_session_unit_cap,
            "credit": None,
            "available": False,
            "reason": None,
        }
        if not st["live_enabled"]:
            st["reason"] = "Live mode is off on this server (no API key). Recorded samples work without it."
            return st
        if st["budget_left"] < need_units:
            st["reason"] = "The judging budget for live calls is used up. Recorded samples still work."
            return st
        if st["ip_sessions_today"] >= s.live_sessions_per_ip_day:
            st["reason"] = "Daily live limit for your network reached. Recorded samples still work."
            return st
        c = credit.get()
        st["credit"] = c
        if c is None or c - need_units < s.live_min_credit:
            st["reason"] = "Live calls are paused to protect the API balance. Recorded samples still work."
            return st
        st["available"] = True
        return st

    def engine_for(sess: dict) -> LiveEngine | ReplayEngine:
        if sess["mode"] == "replay":
            return ReplayEngine(samples[sess["sample_id"]]["dir"])
        sid = sess["id"]
        client = live_client()
        if client is None:
            raise HTTPException(503, "Live mode is not available")

        def ledger(op: str, units: int, task_id: str, ok: bool) -> None:
            store.ledger_add(sid, op, units, task_id, ok)
            if ok:
                store.add_units(sid, units)

        return LiveEngine(client, ledger=ledger)

    def ctx_for(sess: dict) -> SessionCtx:
        d = session_dir(sess["id"])
        ctx = SessionCtx((d / "bride.jpg").read_bytes(), (d / "inspiration.jpg").read_bytes())
        ids = (sess.get("state") or {}).get("_ids") or {}
        ctx.ids.update({k: v for k, v in ids.items() if k in ("bride", "inspiration")})
        return ctx

    def public_state(sess: dict) -> dict:
        st = dict(sess.get("state") or {})
        st.pop("_ids", None)
        base = f"/media/{sess['id']}/"
        images = {k: base + v for k, v in (st.get("images") or {}).items()} if not sess.get("deleted_at") else {}
        out = {
            "id": sess["id"], "mode": sess["mode"], "sample_id": sess["sample_id"], "status": sess["status"],
            "step": sess["step"], "error": sess["error"], "units_spent": sess["units_spent"],
            "deleted": bool(sess.get("deleted_at")), "images": images,
        }
        if sess["error"]:
            h = hint_for(sess["error"])
            out["error_hint"] = {"title": h.title, "fix": h.fix}
        if st.get("map"):
            out.update({k: st.get(k) for k in ("map", "recipe", "recipe_base", "edits", "gaps", "gaps_base", "steps",
                                                "shades", "recipe_sha256", "vto_effects", "notes")})
            if sess["mode"] == "replay":
                keys = set(ReplayEngine(samples[sess["sample_id"]]["dir"]).recorded_render_keys())
                out["edit_options"] = pipeline.edit_options(st, keys)
            else:
                room = sess["units_spent"] + UNITS["makeup-vto"] <= s.live_session_unit_cap
                out["edit_options"] = [{**o, "available": room} for o in pipeline.edit_options(st)]
            out["edit_cost_units"] = 0 if sess["mode"] == "replay" else UNITS["makeup-vto"]
        return out

    def run_session(sid: str) -> None:
        sess = store.session(sid)
        if sess is None:
            return
        store.update_session(sid, status="running", step="makeup_transfer")
        try:
            engine = engine_for(sess)
            ctx = ctx_for(sess)
            state = pipeline.build_look(engine, ctx, session_dir(sid))
            state["_ids"] = {k: v for k, v in ctx.ids.items() if k in ("bride", "inspiration")}
            store.update_session(sid, status="ready", step="done", state=state)
        except YouCamError as e:
            store.update_session(sid, status="error", error=e.code)
        except NotRecorded as e:
            store.update_session(sid, status="error", error=f"not_recorded:{e}")
        except Exception as e:  # surface, never swallow
            store.update_session(sid, status="error", error=f"internal:{type(e).__name__}")
            raise

    # ---------------- pages ----------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        ip = client_ip(request)
        return templates.TemplateResponse(request, "index.html", {
            "samples": [m for m in samples.values() if m["recorded"]], "live": live_status(ip)})

    @app.get("/try/{sample_id}")
    def try_sample(sample_id: str, request: Request, background: BackgroundTasks):
        m = samples.get(sample_id)
        if m is None or not m["recorded"]:
            raise HTTPException(404, "unknown sample")
        sid = store.create_session("replay", sample_id, client_ip(request), consent=False)
        d = session_dir(sid)
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(m["dir"] / "bride.jpg", d / "bride.jpg")
        shutil.copy(m["dir"] / "inspiration.jpg", d / "inspiration.jpg")
        background.add_task(run_session, sid)
        return RedirectResponse(f"/s/{sid}", status_code=303)

    @app.get("/live", response_class=HTMLResponse)
    def live_page(request: Request):
        return templates.TemplateResponse(request, "live.html", {"live": live_status(client_ip(request))})

    @app.get("/s/{sid}", response_class=HTMLResponse)
    def session_page(sid: str, request: Request):
        sess = store.session(sid)
        if sess is None:
            raise HTTPException(404, "session not found")
        sample = samples.get(sess["sample_id"] or "")
        return templates.TemplateResponse(request, "session.html", {
            "sid": sid, "mode": sess["mode"], "sample": sample})

    @app.get("/b/{bid}", response_class=HTMLResponse)
    def brief_page(bid: str, request: Request, t: str = ""):
        role = store.role_for(bid, t)
        if role is None:
            raise HTTPException(404, "brief not found")
        return templates.TemplateResponse(request, "brief.html", {"bid": bid, "token": t, "role": role})

    @app.get("/card/{bid}", response_class=HTMLResponse)
    def card_page(bid: str, request: Request, t: str = ""):
        role = store.role_for(bid, t)
        if role is None:
            raise HTTPException(404, "brief not found")
        view = brief_view(bid, role)
        return templates.TemplateResponse(request, "card.html", {"v": view, "token": t,
                                                                 "public_key": signer.public_jwk_like()})

    # ---------------- API ----------------
    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__, "build": build_id(),
                "samples": [k for k, m in samples.items() if m["recorded"]]}

    @app.get("/api/limits")
    def limits(request: Request):
        return live_status(client_ip(request))

    @app.get("/.well-known/lookbrief-attest.json")
    def public_key():
        return signer.public_jwk_like()

    @app.post("/api/live/check")
    async def live_check(photo: UploadFile = File(...), role: str = Form(...)):
        if role not in ("bride", "inspiration"):
            raise HTTPException(400, "role must be bride or inspiration")
        res, _ = photo_check.check(await photo.read(), role)
        return res.to_dict()

    @app.post("/api/live/sessions")
    async def live_session(request: Request, background: BackgroundTasks, bride: UploadFile = File(...),
                           inspiration: UploadFile = File(...), consent: str = Form("")):
        if consent != "yes":
            raise HTTPException(400, "consent is required before uploading a face")
        ip = client_ip(request)
        st = live_status(ip)
        if not st["available"]:
            return JSONResponse({"error": "live_unavailable", "reason": st["reason"]}, status_code=429)
        checks, imgs = {}, {}
        for role, up in (("bride", bride), ("inspiration", inspiration)):
            res, img = photo_check.check(await up.read(), role)
            checks[role] = res.to_dict()
            imgs[role] = img
        if not all(c["ok"] for c in checks.values()):
            return JSONResponse({"error": "photo_check", "checks": checks}, status_code=422)
        sid = store.create_session("live", None, ip, consent=True)
        store.count_ip_session(ip)
        d = session_dir(sid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "bride.jpg").write_bytes(photo_check.to_jpeg(imgs["bride"]))
        (d / "inspiration.jpg").write_bytes(photo_check.to_jpeg(imgs["inspiration"]))
        background.add_task(run_session, sid)
        return {"session_id": sid, "url": f"/s/{sid}", "checks": checks}

    @app.get("/api/sessions/{sid}")
    def get_session(sid: str):
        sess = store.session(sid)
        if sess is None:
            raise HTTPException(404, "session not found")
        return public_state(sess)

    @app.post("/api/sessions/{sid}/edits")
    def edit(sid: str, body: EditIn, request: Request):
        sess = store.session(sid)
        if sess is None or sess["status"] != "ready":
            raise HTTPException(409, "session is not ready")
        state = sess["state"]
        edits = list(state.get("edits") or [])
        if body.action == "reset":
            edits = []
        elif body.action == "undo":
            edits = edits[:-1]
        else:
            if body.zone not in rcp.EDIT_ZONES or body.op not in rcp.EDIT_OPS:
                raise HTTPException(400, "unknown edit")
            edits.append([body.zone, body.op])
        engine = engine_for(sess)
        if sess["mode"] == "live":
            if sess["units_spent"] + UNITS["makeup-vto"] > s.live_session_unit_cap:
                return JSONResponse({"error": "session_cap", "reason": "This live session reached its unit cap."},
                                    status_code=429)
            st = live_status(client_ip(request), need_units=UNITS["makeup-vto"])
            if st["budget_left"] < 1 or (st["credit"] is not None and st["credit"] - 1 < s.live_min_credit):
                return JSONResponse({"error": "live_unavailable", "reason": st["reason"]}, status_code=429)
        try:
            ctx = ctx_for(sess)
            state = pipeline.rerender(engine, ctx, session_dir(sid), state, edits)
        except NotRecorded:
            return JSONResponse({"error": "not_recorded", "reason": "This combination isn't in the recorded set. "
                                 "Undo or try another single edit — or use Live with your own photos."},
                                status_code=409)
        except YouCamError as e:
            h = hint_for(e.code)
            return JSONResponse({"error": e.code, "reason": f"{h.title}. {h.fix}"}, status_code=502)
        store.update_session(sid, state=state)
        return public_state(store.session(sid) or sess)

    @app.post("/api/sessions/{sid}/delete")
    def delete_photos(sid: str):
        sess = store.session(sid)
        if sess is None:
            raise HTTPException(404, "session not found")
        if sess["mode"] != "live":
            raise HTTPException(400, "sample sessions hold no uploaded photos")
        d = session_dir(sid)
        if d.exists():
            shutil.rmtree(d)
        store.update_session(sid, deleted_at=time.time())
        return {"deleted": True}

    @app.get("/sample-media/{sample_id}/{name}")
    def sample_media(sample_id: str, name: str):
        m = samples.get(sample_id)
        if m is None or name not in ("bride.jpg", "inspiration.jpg"):
            raise HTTPException(404)
        return FileResponse(m["dir"] / name, headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/media/{sid}/{name}")
    def media(sid: str, name: str):
        if not SAFE_NAME.match(name) or not re.fullmatch(r"[A-Za-z0-9_-]{8,32}", sid):
            raise HTTPException(404)
        p = session_dir(sid) / name
        if not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "private, max-age=3600"})

    # ---------------- briefs ----------------
    def snapshot_from(sess: dict) -> dict:
        st = sess["state"]
        d = session_dir(sess["id"])
        images = {k: v for k, v in st["images"].items() if (d / v).exists()}
        zones = [{"zone": r["zone"], "label": r["label"], "product_hex": r["product_hex"],
                  "intensity": r["intensity"], "on_face_hex": r["on_face_hex"], "coverage": r["coverage"]}
                 for r in st["shades"]]
        review_zones = [z["zone"] for z in zones]
        if "hair" in st["images"]:
            review_zones.append("hair")
        return {
            "session_id": sess["id"], "mode": sess["mode"], "sample_id": sess["sample_id"],
            "images": images, "images_sha256": {k: attest.sha256_file(d / v) for k, v in images.items()},
            "zones": zones, "review_zones": review_zones, "recipe": st["recipe"],
            "recipe_sha256": st["recipe_sha256"], "edits": st["edits"], "gaps": st["gaps"],
            "map": st["map"], "steps": {k: {kk: v.get(kk) for kk in ("mode", "task_id", "recorded_at", "seconds")}
                                        for k, v in st["steps"].items() if isinstance(v, dict) and "task_id" in v},
        }

    def brief_view(bid: str, role: str) -> dict:
        b = store.brief(bid)
        if b is None:
            raise HTTPException(404)
        v = int(b["version"])
        reviews = store.reviews(bid, v)
        agreed = store.agreements(bid, v)
        snap = b["snapshot"]
        missing = [z for z in snap["review_zones"] if z not in reviews]
        discuss = [z for z, r in reviews.items() if r["status"] == "discuss"]
        base = f"/media/{snap['session_id']}/"
        return {
            "id": bid, "role": role, "version": v, "snapshot": snap,
            "images": {k: base + p for k, p in snap["images"].items()},
            "reviews": reviews, "review_labels": REVIEW_LABELS,
            "agreed": {r: iso(t) for r, t in agreed.items()},
            "missing_reviews": missing, "open_discussions": discuss,
            "can_agree": (role == "bride") or (not missing and not discuss),
            "attestation": store.attestation(bid, v),
            "public_url": s.public_url,
        }

    @app.post("/api/sessions/{sid}/brief")
    def create_brief(sid: str):
        sess = store.session(sid)
        if sess is None or sess["status"] != "ready":
            raise HTTPException(409, "session is not ready")
        b = store.create_brief(sid, snapshot_from(sess))
        return {"brief_id": b["id"], "bride_url": f"/b/{b['id']}?t={b['bride_token']}",
                "artist_url": f"/b/{b['id']}?t={b['artist_token']}"}

    @app.get("/api/briefs/{bid}")
    def get_brief(bid: str, t: str = ""):
        role = store.role_for(bid, t)
        if role is None:
            raise HTTPException(404, "brief not found")
        return brief_view(bid, role)

    @app.post("/api/briefs/{bid}/review")
    def review(bid: str, body: ReviewIn):
        role = store.role_for(bid, body.t)
        if role != "artist":
            raise HTTPException(403, "only the artist link can review zones")
        b = store.brief(bid)
        assert b is not None
        if body.zone not in b["snapshot"]["review_zones"] or body.status not in REVIEW_STATUSES:
            raise HTTPException(400, "unknown zone or status")
        if store.attestation(bid, int(b["version"])):
            raise HTTPException(409, "this version is already agreed and signed")
        store.set_review(bid, int(b["version"]), body.zone, body.status, body.note.strip())
        return brief_view(bid, role)

    @app.post("/api/briefs/{bid}/revise")
    def revise(bid: str, body: BriefIn):
        role = store.role_for(bid, body.t)
        if role != "bride":
            raise HTTPException(403, "only the bride link can update the brief")
        b = store.brief(bid)
        assert b is not None
        sess = store.session(b["snapshot"]["session_id"])
        if sess is None or sess["status"] != "ready":
            raise HTTPException(409, "session is not ready")
        store.revise_brief(bid, snapshot_from(sess))
        return brief_view(bid, role)

    @app.post("/api/briefs/{bid}/agree")
    def agree(bid: str, body: BriefIn):
        role = store.role_for(bid, body.t)
        if role is None:
            raise HTTPException(404, "brief not found")
        view = brief_view(bid, role)
        if not view["can_agree"]:
            raise HTTPException(409, "review every zone first; 'Let's discuss' must be resolved")
        v = view["version"]
        store.agree(bid, v, role)
        agreed = store.agreements(bid, v)
        view = brief_view(bid, role)
        if {"bride", "artist"} <= set(agreed) and not view["missing_reviews"] and not view["open_discussions"] \
                and not view["attestation"]:
            snap = view["snapshot"]
            zones = []
            for z in snap["review_zones"]:
                r = view["reviews"][z]
                zi = next((x for x in snap["zones"] if x["zone"] == z), {"zone": z, "label": "Hair"})
                zones.append({**zi, "status": r["status"], "note": r["note"]})
            payload = {
                "type": "lookbrief.agreement.v1", "statement": attest.STATEMENT, "brief_id": bid, "version": v,
                "issuer": s.public_url or "local", "issued_at": iso(time.time()),
                "agreed_at": {r: iso(t) for r, t in agreed.items()}, "zones": zones,
                "recipe": snap["recipe"], "recipe_sha256": snap["recipe_sha256"],
                "images_sha256": snap["images_sha256"], "youcam_steps": snap["steps"], "mode": snap["mode"],
            }
            store.save_attestation(bid, v, signer.sign(payload))
            view = brief_view(bid, role)
        return view

    @app.get("/api/briefs/{bid}/attestation.json")
    def attestation_json(bid: str, t: str = ""):
        role = store.role_for(bid, t)
        if role is None:
            raise HTTPException(404, "brief not found")
        b = store.brief(bid)
        assert b is not None
        att = store.attestation(bid, int(b["version"]))
        if att is None:
            raise HTTPException(404, "not agreed yet")
        return JSONResponse(att, headers={"Content-Disposition": f'attachment; filename="look-brief-{bid}.json"'})

    def cleanup_expired() -> int:
        n = 0
        for sid in store.expired_live_sessions(time.time() - s.upload_ttl_hours * 3600):
            d = session_dir(sid)
            if d.exists():
                shutil.rmtree(d)
            store.update_session(sid, deleted_at=time.time())
            n += 1
        return n

    cleanup_expired()  # on start: remove live uploads older than the TTL

    app.state.store = store
    app.state.settings = s
    app.state.cleanup_expired = cleanup_expired
    app.state.run_session = run_session
    return app
