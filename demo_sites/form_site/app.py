"""CI-safe 4-step form wizard target — pruning-heavy long-horizon test."""
from __future__ import annotations

from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for

STEPS = ("contact", "address", "preferences", "review")


def createApp() -> Flask:
    app = Flask(__name__)
    app.secret_key = "cutiee-demo-only"

    @app.get("/")
    def index():
        return redirect(url_for("step", name = STEPS[0]))

    @app.route("/step/<name>", methods = ["GET", "POST"])
    def step(name: str):
        if name not in STEPS:
            return ("not found", 404)
        index = STEPS.index(name)
        if request.method == "POST":
            session.setdefault("data", {})[name] = request.form.to_dict()
            session.modified = True
            if index + 1 < len(STEPS):
                return redirect(url_for("step", name = STEPS[index + 1]))
            return redirect(url_for("submit"))
        return render_template_string(_TEMPLATE, name = name, index = index, total = len(STEPS), data = session.get("data", {}).get(name, {}))

    @app.post("/submit")
    def submit():
        return jsonify({"ok": True, "data": session.get("data", {})})

    return app


_TEMPLATE = """
<!doctype html><html><head><title>Wizard step {{ index + 1 }}</title>
<style>body{font-family:system-ui,sans-serif;padding:24px;background:#f8fafc;}
form{display:grid;gap:8px;max-width:420px;}
input,textarea{padding:8px 10px;border:1px solid #cbd5e1;border-radius:6px;font:inherit;}
button{padding:8px 14px;background:#6C86C0;color:#fff;border:none;border-radius:6px;cursor:pointer;}</style></head>
<body><h1>Wizard {{ index + 1 }} / {{ total }} · {{ name }}</h1>
<form method="post">
  {% if name == 'contact' %}
    <label>Name<input name="name" id="name" value="{{ data.get('name', '') }}" required></label>
    <label>Email<input name="email" id="email" type="email" value="{{ data.get('email', '') }}" required></label>
  {% elif name == 'address' %}
    <label>Street<input name="street" id="street" value="{{ data.get('street', '') }}" required></label>
    <label>City<input name="city" id="city" value="{{ data.get('city', '') }}" required></label>
  {% elif name == 'preferences' %}
    <label>Newsletter?<input name="newsletter" id="newsletter" type="checkbox" {% if data.get('newsletter') %}checked{% endif %}></label>
    <label>Notes<textarea name="notes" id="notes">{{ data.get('notes', '') }}</textarea></label>
  {% elif name == 'review' %}
    <p>Confirm and submit. Press the button below.</p>
  {% endif %}
  <button type="submit" id="next">{% if index + 1 == total %}Finish{% else %}Next{% endif %}</button>
</form>
</body></html>
"""


if __name__ == "__main__":
    createApp().run(host = "127.0.0.1", port = 5003, debug = True)
