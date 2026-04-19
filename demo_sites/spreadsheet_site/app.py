"""CI-safe spreadsheet target — 10x5 grid the agent can edit, sort, and sum."""
from __future__ import annotations

from copy import deepcopy

from flask import Flask, jsonify, render_template_string, request

ROWS = 10
COLS = 5
INITIAL_CELLS: list[list[str]] = [
    [f"R{r}C{c}" if (r, c) != (0, 0) else "Quarter" for c in range(COLS)]
    for r in range(ROWS)
]


def createApp(initialState: list[list[str]] | None = None) -> Flask:
    app = Flask(__name__)
    state: list[list[str]] = deepcopy(initialState or INITIAL_CELLS)

    @app.get("/")
    def index() -> str:
        return render_template_string(_TEMPLATE, rows = state)

    @app.post("/edit/<int:row>/<int:col>")
    def edit(row: int, col: int):
        value = request.form.get("value", "")
        if 0 <= row < ROWS and 0 <= col < COLS:
            state[row][col] = value
        return jsonify({"row": row, "col": col, "value": value})

    @app.post("/sort/<int:col>")
    def sort_col(col: int):
        if 0 <= col < COLS:
            header, body = state[0], state[1:]
            body.sort(key = lambda row: row[col])
            state[:] = [header] + body
        return jsonify({"col": col, "ok": True})

    @app.post("/sum/<int:col>")
    def sum_col(col: int):
        total = 0.0
        for row in state[1:]:
            try:
                total += float(row[col])
            except (TypeError, ValueError):
                continue
        return jsonify({"col": col, "sum": total})

    return app


_TEMPLATE = """
<!doctype html>
<html><head><title>CUTIEE spreadsheet demo</title>
<style>body{font-family:system-ui,sans-serif;padding:24px;background:#f8fafc;}
table{border-collapse:collapse;}
th,td{border:1px solid #cbd5e1;padding:6px 10px;font-size:13px;min-width:80px;}
button{margin:4px;padding:6px 12px;border:1px solid #6C86C0;background:#fff;border-radius:8px;cursor:pointer;}
input{width:90%;border:none;background:transparent;font-size:13px;}</style></head>
<body><h1>Spreadsheet</h1>
<table id="grid">
<thead><tr>{% for col in range(rows[0]|length) %}<th>Col {{ col }}</th>{% endfor %}</tr></thead>
<tbody>
{% for row in rows %}
<tr>
{% for cell in row %}
<td><input data-row="{{ loop.index0 }}" data-col="{{ loop.index0 }}" value="{{ cell }}" id="cell-{{ loop.index0 }}-{{ loop.index0 }}" /></td>
{% endfor %}
</tr>
{% endfor %}
</tbody></table>
<div>
{% for col in range(rows[0]|length) %}
<button id="sort-{{ col }}" onclick="fetch('/sort/{{ col }}', {method:'POST'}).then(()=>location.reload())">Sort by Col {{ col }}</button>
{% endfor %}
</div>
</body></html>
"""


if __name__ == "__main__":
    createApp().run(host = "127.0.0.1", port = 5001, debug = True)
