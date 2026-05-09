import os
from datetime import datetime, timedelta

from flask import Flask, jsonify, request

from pbx_portal.metrics import build_dashboard
from pbx_portal.sources import CdrRepository, FreePbxCdrSource, QueueLogRepository, sync_freepbx_to_portal


def create_app():
    app = Flask(__name__)
    cdr_repo = CdrRepository.from_env()
    queue_repo = QueueLogRepository.from_env()

    @app.get("/")
    def index():
        return jsonify(
            {
                "service": "pbx-portal-api",
                "dashboard": "Run the Next.js frontend in ./frontend",
            }
        )

    @app.get("/api/dashboard")
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

    @app.post("/api/sync")
    def sync():
        days = request.args.get("days", type=int) or 1
        end = _parse_date(request.args.get("end")) or datetime.utcnow()
        start = _parse_date(request.args.get("start")) or (end - timedelta(days=days))
        try:
            result = sync_freepbx_to_portal(start=start, end=end)
        except RuntimeError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, **result})

    @app.get("/health")
    def health():
        return jsonify(
            {
                "ok": True,
                "source": cdr_repo.source_name,
                "pbx_configured": FreePbxCdrSource.from_env().configured,
            }
        )

    return app


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
