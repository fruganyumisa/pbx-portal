import os
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, jsonify, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from pbx_portal.auth import AuthService
from pbx_portal.metrics import build_dashboard
from pbx_portal.sources import CdrRepository, FreePbxCdrSource, QueueLogRepository, sync_freepbx_to_portal

_sync_lock = threading.Lock()
_scheduler_started = False


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "change-me-in-production")
    if _env_bool("TRUST_PROXY", False):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=_env_bool("SESSION_COOKIE_HTTPONLY", True),
        SESSION_COOKIE_SAMESITE=os.getenv("SESSION_COOKIE_SAMESITE", "Lax"),
        SESSION_COOKIE_SECURE=_env_bool("SESSION_COOKIE_SECURE", False),
    )
    cdr_repo = CdrRepository.from_env()
    queue_repo = QueueLogRepository.from_env()
    auth = AuthService.from_env()

    @app.get("/")
    def index():
        return jsonify(
            {
                "service": "pbx-portal-api",
                "dashboard": "Run the Next.js frontend in ./frontend",
            }
        )

    @app.post("/api/auth/login")
    def login():
        payload = request.get_json(silent=True) or {}
        user = auth.authenticate(payload.get("username", ""), payload.get("password", ""))
        if not user:
            return jsonify({"ok": False, "error": "Invalid username or password"}), 401
        session["user_id"] = user["id"]
        return jsonify({"ok": True, "user": user})

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.get("/api/auth/me")
    def me():
        user = _current_user(auth)
        if not user:
            return jsonify({"ok": False, "error": "Authentication required"}), 401
        return jsonify({"ok": True, "user": user})

    @app.get("/api/users")
    @require_role(auth, "admin")
    def users():
        return jsonify({"users": auth.list_users()})

    @app.post("/api/users")
    @require_role(auth, "admin")
    def create_user():
        payload = request.get_json(silent=True) or {}
        try:
            user = auth.create_user(
                username=payload.get("username", "").strip(),
                password=payload.get("password", ""),
                role=payload.get("role", "user"),
                full_name=payload.get("full_name", "").strip(),
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception as exc:
            return jsonify({"ok": False, "error": "Could not create user"}), 400
        return jsonify({"ok": True, "user": user}), 201

    @app.patch("/api/users/<user_id>")
    @require_role(auth, "admin")
    def update_user(user_id):
        payload = request.get_json(silent=True) or {}
        try:
            requested_enabled = _optional_bool(payload, "enabled")
            requested_role = payload.get("role")
            actor = _current_user(auth)
            if actor and actor["id"] == str(user_id):
                if requested_enabled is False:
                    return jsonify({"ok": False, "error": "You cannot disable your own account"}), 400
                if requested_role is not None and requested_role != "admin":
                    return jsonify({"ok": False, "error": "You cannot remove your own admin role"}), 400
            user = auth.update_user(
                user_id=user_id,
                username=payload.get("username"),
                full_name=payload.get("full_name"),
                role=requested_role,
                enabled=requested_enabled,
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({"ok": False, "error": "Could not update user"}), 400
        return jsonify({"ok": True, "user": user})

    @app.post("/api/users/<user_id>/password")
    @require_role(auth, "admin")
    def change_user_password(user_id):
        payload = request.get_json(silent=True) or {}
        try:
            auth.set_password(user_id=user_id, password=payload.get("password", ""))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({"ok": False, "error": "Could not change password"}), 400
        return jsonify({"ok": True})

    @app.delete("/api/users/<user_id>")
    @require_role(auth, "admin")
    def delete_user(user_id):
        actor = _current_user(auth)
        if actor and actor["id"] == str(user_id):
            return jsonify({"ok": False, "error": "You cannot delete your own account"}), 400
        try:
            auth.delete_user(user_id=user_id)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({"ok": False, "error": "Could not delete user"}), 400
        return jsonify({"ok": True})

    @app.get("/api/dashboard")
    @require_auth(auth)
    def dashboard():
        end = _parse_date(request.args.get("end")) or datetime.utcnow()
        start = _parse_date(request.args.get("start")) or (end - timedelta(days=7))
        queue = request.args.get("queue") or None
        agent = request.args.get("agent") or None

        try:
            payload = build_dashboard(
                cdr_repo=cdr_repo,
                queue_repo=queue_repo,
                start=start,
                end=end,
                queue=queue,
                agent=agent,
            )
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(payload)

    @app.get("/api/calls")
    @require_auth(auth)
    def calls():
        end = _parse_date(request.args.get("end")) or datetime.utcnow()
        start = _parse_date(request.args.get("start")) or (end - timedelta(days=7))
        queue = request.args.get("queue") or None
        agent = request.args.get("agent") or None
        source = request.args.get("source") or None
        direction = request.args.get("direction") or None
        status = request.args.get("status") or None
        page = request.args.get("page", type=int) or 1
        per_page = request.args.get("per_page", type=int) or 50
        try:
            payload = cdr_repo.fetch_call_page(
                start=start,
                end=end,
                queue=queue,
                agent=agent,
                source=source,
                direction=direction,
                status=status,
                page=page,
                per_page=per_page,
            )
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify(payload)

    @app.post("/api/sync")
    @require_role(auth, "admin")
    def sync():
        days = request.args.get("days", type=int)
        end = _parse_date(request.args.get("end")) or datetime.utcnow()
        explicit_start = _parse_date(request.args.get("start"))
        fallback_start = end - timedelta(days=days or 1)
        try:
            result = _run_sync(start=explicit_start, end=end, fallback_start=fallback_start)
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 502
        except Exception:
            app.logger.exception("Sync failed unexpectedly")
            return jsonify({"ok": False, "error": "Sync failed unexpectedly"}), 500
        return jsonify({"ok": True, **result})

    @app.get("/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "source": cdr_repo.source_name,
                "pbx_configured": FreePbxCdrSource.from_env().configured,
                "auto_sync_enabled": _auto_sync_enabled(),
            }
        )

    _start_scheduler_once(app)
    return app


def require_auth(auth):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not _current_user(auth):
                return jsonify({"ok": False, "error": "Authentication required"}), 401
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_role(auth, role):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = _current_user(auth)
            if not user:
                return jsonify({"ok": False, "error": "Authentication required"}), 401
            if user["role"] != role:
                return jsonify({"ok": False, "error": "Forbidden"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def _current_user(auth):
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        user = auth.get_user_by_id(user_id)
    except ValueError:
        session.clear()
        return None
    if not user or not user["enabled"]:
        session.clear()
        return None
    return {
        "id": str(user["id"]),
        "username": user["username"],
        "role": user["role"],
        "full_name": user["full_name"],
        "enabled": user["enabled"],
    }


def _run_sync(start=None, end=None, fallback_start=None):
    if not _sync_lock.acquire(blocking=False):
        raise RuntimeError("Sync is already running")
    try:
        return sync_freepbx_to_portal(start=start, end=end, fallback_start=fallback_start)
    finally:
        _sync_lock.release()


def _start_scheduler_once(app):
    global _scheduler_started
    if _scheduler_started or not _auto_sync_enabled():
        return
    _scheduler_started = True
    thread = threading.Thread(target=_sync_loop, args=(app,), daemon=True)
    thread.start()


def _sync_loop(app):
    interval = int(os.getenv("SYNC_INTERVAL_SECONDS", "600"))
    initial_delay = int(os.getenv("SYNC_INITIAL_DELAY_SECONDS", "20"))
    time.sleep(initial_delay)
    while True:
        try:
            with app.app_context():
                end = datetime.utcnow()
                fallback_start = end - timedelta(days=int(os.getenv("INITIAL_SYNC_DAYS", "1")))
                _run_sync(end=end, fallback_start=fallback_start)
        except Exception as exc:
            app.logger.warning("Background sync failed: %s", exc)
        time.sleep(interval)


def _auto_sync_enabled():
    return os.getenv("AUTO_SYNC_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _optional_bool(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{key} must be a boolean")


def _env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
