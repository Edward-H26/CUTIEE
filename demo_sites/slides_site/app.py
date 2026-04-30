"""CI-safe slides target — 3 initial slides; add, edit, reorder."""

from __future__ import annotations

from dataclasses import dataclass, field

from flask import Flask, jsonify, render_template_string, request


@dataclass
class Slide:
    title: str
    body: str = ""
    id: int = 0


@dataclass
class SlideStore:
    slides: list[Slide] = field(default_factory=list)
    nextId: int = 1

    def add(self, title: str, body: str) -> Slide:
        slide = Slide(title=title, body=body, id=self.nextId)
        self.nextId += 1
        self.slides.append(slide)
        return slide

    def reorder(self, fromIndex: int, toIndex: int) -> None:
        if 0 <= fromIndex < len(self.slides) and 0 <= toIndex < len(self.slides):
            slide = self.slides.pop(fromIndex)
            self.slides.insert(toIndex, slide)


def createApp() -> Flask:
    app = Flask(__name__)
    store = SlideStore()
    store.add("Welcome", "Q1 plan overview")
    store.add("Status", "Six tasks shipped")
    store.add("Next steps", "Cut a release on Friday")

    @app.get("/")
    def index() -> str:
        return render_template_string(_TEMPLATE, slides=store.slides)

    @app.post("/slides")
    def add_slide():
        title = request.form.get("title", "Untitled")
        body = request.form.get("body", "")
        slide = store.add(title, body)
        return jsonify({"id": slide.id, "title": slide.title})

    @app.post("/slides/<int:slide_id>/edit")
    def edit_slide(slide_id: int):
        for slide in store.slides:
            if slide.id == slide_id:
                slide.title = request.form.get("title", slide.title)
                slide.body = request.form.get("body", slide.body)
                return jsonify({"ok": True})
        return jsonify({"ok": False}), 404

    @app.post("/slides/reorder")
    def reorder():
        fromIdx = int(request.form.get("from", 0))
        toIdx = int(request.form.get("to", 0))
        store.reorder(fromIdx, toIdx)
        return jsonify({"ok": True})

    return app


_TEMPLATE = """
<!doctype html><html><head><title>CUTIEE slides demo</title>
<style>body{font-family:system-ui,sans-serif;padding:24px;background:#f8fafc;}
.slide{border:1px solid #cbd5e1;padding:14px;margin:10px 0;border-radius:10px;background:#fff;}
.slide h2{margin:0 0 4px;}
form{margin-top:14px;display:grid;gap:6px;max-width:480px;}
input,textarea{padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px;font:inherit;}
button{padding:6px 12px;background:#6C86C0;color:#fff;border:none;border-radius:6px;cursor:pointer;}</style></head>
<body><h1>Slides</h1>
{% for slide in slides %}
<div class="slide" id="slide-{{ slide.id }}" data-index="{{ loop.index0 }}">
  <h2>{{ slide.title }}</h2>
  <p>{{ slide.body }}</p>
</div>
{% endfor %}
<form method="post" action="/slides">
  <label>Title<input name="title" id="new-title" required></label>
  <label>Body<textarea name="body" id="new-body"></textarea></label>
  <button type="submit" id="add-slide">Add slide</button>
</form>
</body></html>
"""


if __name__ == "__main__":
    createApp().run(host="127.0.0.1", port=5002, debug=True)
