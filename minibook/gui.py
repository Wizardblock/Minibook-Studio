"""NiceGUI interface (SYS-03). A thin view over AppController: every decision lives in controller.py.

NOTE: this file has not been launched against a real NiceGUI install (the build environment could
not install it). It was exercised against a stand-in `nicegui` module only. Run it with
`python minibook_gui.py` and report anything that errors.
"""
from __future__ import annotations

import base64
import io
import sys
import time
from pathlib import Path

from PIL import Image

from nicegui import run, ui

from . import covers, csvimport as c, imaging, layout, preview as pv, settings as S, units, workspace
from .controller import (MAX_ZOOM, STATUS_OPTIONS, YEAR_ALL, AppController, pdf_path)

APP_TITLE = "MiniBook Studio"
NATIVE = False      # set by main(): True when running in a standalone window
QUALITY_COLOR = {"good": "green", "ok": "orange", "low": "red", "unknown": "grey"}
QUALITY_TEXT = {"good": "Sharp", "ok": "OK", "low": "Low-res", "unknown": "?"}
PREVIEW_BASE_DPI = 110     # a sheet drawn at this resolution is shown at 100% zoom
ZOOM_TIERS = ((1.25, PREVIEW_BASE_DPI), (2.0, 165), (99.0, 220))   # (up to this zoom, draw at this dpi)


def dpi_for_zoom(zoom: float) -> int:
    """Zoomed-in views are drawn at a higher resolution so they stay sharp; the cost rises with it."""
    return next(dpi for limit, dpi in ZOOM_TIERS if zoom <= limit)


def preview_url(img: Image.Image) -> str:
    """The sheet as a data URL. JPEG at full colour detail is several times faster to encode than PNG
    and the thin cut marks stay clean at this quality."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=92, subsampling=0)
    return f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"
PREVIEW_DELAY = 0.5        # seconds of quiet after the last change before the preview is redrawn
BLANK_IMAGE = ("data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
# Sizes the two Preview panes to exactly the space between the header and the zoom bar, and switches the
# page's own scrolling off while they are showing, so the only scroll bars are the two inside the panes.
FIT_SCRIPT = """<script>
window.mbOn = false;
window.mbFit = function (on) {
  window.mbOn = on;
  document.documentElement.style.overflow = on ? 'hidden' : '';
  document.body.style.overflow = on ? 'hidden' : '';
  var el = document.querySelector('.mb-preview-row');
  if (!on || !el) return;
  window.scrollTo(0, 0);
  var f = document.querySelector('.q-footer');
  var fh = (f && f.offsetHeight) || 0;
  el.style.height = Math.max(200, window.innerHeight - el.getBoundingClientRect().top - fh) + 'px';
};
window.addEventListener('resize', function () { if (window.mbOn) window.mbFit(true); });
</script>"""
DATE_FORMAT_CHOICES = {"full": "Day, month and year (Mar 5, 2026)", "month": "Month and year (Mar 2026)",
                       "year": "Year only (2026)"}


# -- small helpers ------------------------------------------------------------------------
def data_url(img: Image.Image, max_side: int | None = None, fmt: str = "JPEG") -> str:
    """Embed a PIL image in the page without needing a file server."""
    img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, fmt, **({"quality": 85} if fmt == "JPEG" else {}))
    mime = "image/jpeg" if fmt == "JPEG" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


async def read_upload(e) -> tuple[bytes, str]:
    """Works with both upload event shapes: older (`e.content`, `e.name`) and newer (`e.file`)."""
    f = getattr(e, "file", None)
    if f is not None:
        data = f.read()
        if hasattr(data, "__await__"):
            data = await data
        return data, getattr(f, "name", "") or getattr(e, "name", "")
    return e.content.read(), getattr(e, "name", "")


def _first_path(result) -> str | None:
    """The OS save dialog returns a string, a tuple/list of strings, or nothing (cancelled)."""
    if not result:
        return None
    if isinstance(result, (list, tuple)):
        return str(result[0]) if result else None
    return str(result)


async def choose_save_path(initial_dir: str, filename: str, kind: str = "pdf") -> str | None:
    """One save dialog for folder + file name (EXP-08). Returns the chosen path, or None if cancelled.

    In the standalone window this is the operating system's own Save As dialog. In the browser
    fallback there is no OS dialog to call, so a small in-page one asks for the folder and name.
    """
    if NATIVE:
        try:
            import webview
            from nicegui import app
            dialog_kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
            res = await app.native.main_window.create_file_dialog(
                dialog_kind, directory=initial_dir, save_filename=filename,
                file_types={"json": ("JSON files (*.json)",), "workspace": ("MiniBook workspace (*.minibook)",),
                              "svg": ("SVG files (*.svg)",)}
                .get(kind, ("PDF files (*.pdf)",)))
            return _first_path(res)
        except Exception as err:      # fall through to the in-page dialog rather than lose the export
            ui.notify(f"The system save dialog did not open ({err}); using the simple one.", type="warning")
    with ui.dialog() as dlg, ui.card().classes("w-[min(560px,95vw)]"):
        ui.label({"json": "Save settings", "workspace": "Save workspace", "svg": "Save SVG"}.get(kind, "Save PDF")).classes("text-lg font-bold")
        folder = ui.input(label="Folder", value=initial_dir).classes("w-full")
        name = ui.input(label="File name", value=filename).classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Cancel", on_click=lambda: dlg.submit(None)).props("flat")
            ui.button("Save", icon="save", on_click=lambda: dlg.submit(
                str(_with_extension(Path(folder.value or initial_dir).expanduser() / (name.value or filename), kind)))
            ).props("color=primary")
    result = await dlg
    dlg.delete()
    return result


def _with_extension(path: Path, kind: str) -> Path:
    if kind == "pdf":
        return pdf_path(path)
    ext = {"workspace": ".minibook", "svg": ".svg"}.get(kind, ".json")
    return path if path.suffix.lower() == ext else path.with_name(path.name + ext)


def fmt_num(v: float, places: int = 3) -> float:
    return round(v, places)


# -- the page ---------------------------------------------------------------------------------
def build_page(ctl: AppController) -> None:
    ui.colors(primary="#2f5d50")
    ui.add_head_html(FIT_SCRIPT)
    progress_state = {"i": 0, "n": 1, "title": "", "busy": False}
    row_boxes: dict[str, object] = {}      # book id -> the container holding that book's row
    current = {"book": None}               # the book open in the cover dialog
    wrap_ui: dict[str, object] = {}
    # live preview: `dirty` = something changed since the last drawing; `gen` is bumped by every new
    # request so a drawing that is still running notices it is out of date and stops; `due` is when the
    # quiet pause after the last change ends.
    pv_state = {"dirty": True, "gen": 0, "due": None, "page": 0, "tab": "books", "zoom": 1.0,
                "shown_dpi": PREVIEW_BASE_DPI, "base_px": 935.0}
    pv_ui: dict[str, object] = {}

    # ---------- refreshable pieces ----------
    @ui.refreshable
    def problems_label():
        problems = ctl.settings.validate()
        for p in problems:
            ui.label(p).classes("text-red-600 text-sm")

    @ui.refreshable
    def summary_label():
        s = ctl.summary_counts()
        txt = f"{s['selected']} of {s['shown']} books selected"
        if s["pages_estimate"]:
            txt += f" • about {s['pages_estimate']} page(s)"
        ui.label(txt).classes("text-sm text-gray-600")

    def sync_wrap():
        sw, hint = wrap_ui.get("switch"), wrap_ui.get("hint")
        if sw is None:
            return
        ok = ctl.wrap_available()
        sw.set_enabled(ok)
        hint.set_text("" if ok else "Needs a thicker spine or a smaller 'Smallest text'.")

    # ---------- live preview (EXP-07) ----------
    def touch():
        """Something the preview shows has changed. On the Books tab that only makes a note: nothing is
        drawn until the Preview tab is opened, so changing many covers never triggers a redraw."""
        pv_state["dirty"] = True

    def request_preview(delay: float = PREVIEW_DELAY):
        pv_state["gen"] += 1                     # a drawing in progress is now out of date: let it stop
        pv_state["due"] = time.monotonic() + delay
        timer_pv = pv_ui.get("timer")
        if timer_pv is not None:
            timer_pv.activate()

    def changed():
        """A setting or selection changed: redraw after a short pause, but only if the preview is showing."""
        touch()
        if pv_state["tab"] == "preview":
            request_preview()

    async def poll_preview():
        due = pv_state["due"]
        if due is None or time.monotonic() < due:
            return
        pv_state["due"] = None
        pv_ui["timer"].deactivate()
        await render_preview()

    def show_preview_message(note: str = "", error: str = ""):
        pv_ui["note"].set_text(note)
        pv_ui["error"].set_text(error)
        pv_ui["image"].set_visibility(not (note or error))

    async def render_preview():
        pv_state["dirty"] = False
        my = pv_state["gen"]
        page = pv_state["page"]
        used_dpi = ctl.preview.dpi
        pv_ui["busy"].set_text("Updating preview...")
        try:
            res = await run.io_bound(ctl.preview_page, page, lambda: pv_state["gen"] == my)
            if res is not None:
                src = await run.io_bound(preview_url, res.image)
        except pv.PreviewCancelled:
            pv_state["dirty"] = True              # a newer request is already waiting
            return
        except layout.LayoutError as err:
            pv_ui["busy"].set_text("")
            show_preview_message(error=f"Cannot draw the preview: {err}")
            return
        except Exception as err:
            pv_ui["busy"].set_text("")
            show_preview_message(error=f"The preview failed: {err}")
            return
        pv_ui["busy"].set_text("")
        if my != pv_state["gen"]:                 # changed again while drawing
            pv_state["dirty"] = True
            return
        if res is None:
            pv_ui["page_label"].set_text("No books selected")
            pv_ui["prev"].set_enabled(False)
            pv_ui["next"].set_enabled(False)
            show_preview_message(note="Nothing to show yet: select some books on the Books tab.")
            return
        pv_state["page"] = res.page
        pv_state["shown_dpi"] = used_dpi
        pv_state["base_px"] = res.image.width * PREVIEW_BASE_DPI / used_dpi
        pv_ui["image"].set_source(src)
        apply_zoom()
        pv_ui["page_label"].set_text(f"Page {res.page + 1} of {res.pages}")
        pv_ui["prev"].set_enabled(res.page > 0)
        pv_ui["next"].set_enabled(res.page + 1 < res.pages)
        pv_ui["stats"].set_text(f"{res.books_on_page} book(s) on this page  •  click one to change its cover")
        show_preview_message()

    def apply_zoom():
        """Size of the picture on screen. Only the shown width changes; the sheet is not redrawn."""
        z = pv_state["zoom"]
        pv_ui["image"].style(f"width: {pv_state['base_px'] * z:.0f}px; max-width: none; flex-shrink: 0")
        pv_ui["zoom_label"].set_text(f"{round(z * 100)}%")

    def set_zoom(value: float):
        pv_state["zoom"] = max(0.25, min(3.0, float(value)))
        apply_zoom()
        dpi = dpi_for_zoom(pv_state["zoom"])
        if dpi != ctl.preview.dpi:                 # crossing into (or out of) the sharper drawing
            ctl.preview.dpi = dpi
            changed()
        if pv_ui.get("slider") is not None and pv_ui["slider"].value != round(pv_state["zoom"] * 100):
            pv_ui["slider"].set_value(round(pv_state["zoom"] * 100))

    async def go_page(delta: int):
        pv_state["page"] = max(0, pv_state["page"] + delta)
        pv_state["gen"] += 1
        await render_preview()

    async def on_tab(e):
        pv_state["tab"] = "preview" if e.value == "preview" else "books"
        showing = pv_state["tab"] == "preview"
        pv_ui["footer"].set_value(showing)                          # the zoom bar belongs to the preview
        # size the panes now and again once the zoom bar has slid into place
        ui.run_javascript(f"window.mbFit({str(showing).lower()}); "
                          f"setTimeout(function(){{window.mbFit({str(showing).lower()})}}, 250);")
        if pv_state["tab"] == "preview" and pv_state["dirty"]:
            pv_state["gen"] += 1
            await render_preview()                # opening the tab draws at once, without the pause

    async def on_preview_click(e):
        if getattr(e, "type", "click") != "click":
            return
        k = ctl.preview.dpi / pv_state["shown_dpi"]       # the picture on screen may be from the other resolution
        book = ctl.preview_book_at(pv_state["page"], float(e.image_x) * k, float(e.image_y) * k)
        if book is not None:
            await open_cover_dialog(book)

    def apply(**changes):
        ctl.update_settings(**changes)
        problems_label.refresh()
        summary_label.refresh()
        sync_wrap()
        changed()

    def num_field(label, value_mm, key, step=0.05, min_=0.0):
        """A number box shown in the chosen unit and stored in mm."""
        def on_change(e):
            if e.value is None:
                return
            apply(**{key: ctl.hide(float(e.value))})
        px = ctl.settings.unit == "px"
        ui.number(label=label + (" (px)" if px else ""), value=fmt_num(ctl.show(value_mm), 1 if px else 3),
                  step=1 if px else step, min=min_, format="%.1f" if px else "%.3f",
                  on_change=on_change).classes("w-full")

    @ui.refreshable
    def settings_panel():
        s = ctl.settings
        ui.label("Book size").classes("text-sm font-semibold mt-1")

        def on_unit(e):
            apply(unit=e.value)
            settings_panel.refresh()
        ui.radio({"in": "Inches", "mm": "Millimeters", "px": "Pixels"}, value=s.unit,
                 on_change=on_unit).props("inline dense")
        if s.unit == "px":
            ui.label(f"Pixels at {s.dpi} dpi (see Print quality).").classes("text-xs text-gray-500")

        def on_mode(e):
            apply(size_mode=e.value)
            settings_panel.refresh()
        ui.radio({"width": "Height + width", "aspect": "Height + aspect ratio"}, value=s.size_mode,
                 on_change=on_mode).props("dense")
        num_field("Height", s.height_mm, "height_mm")
        if s.size_mode == "width":
            num_field("Width (front cover)", s.width_mm, "width_mm")
        else:
            def on_aspect(e):
                try:
                    apply(aspect=units.parse_aspect(e.value))
                except (ValueError, ZeroDivisionError):
                    pass
            ui.input(label="Aspect ratio (width:height, e.g. 2:3)", value=f"{s.aspect:.3f}",
                     on_change=on_aspect).classes("w-full")
        num_field("Thickness (spine)", s.thickness_mm, "thickness_mm")

        with ui.expansion("Scale calculator", icon="straighten").classes("w-full"):
            # the real book is measured in the unit chosen above (pixels make no sense for a real book: inches then)
            mm = s.unit == "mm"
            k = 25.4 if mm else 1.0
            name = "mm" if mm else "in"
            ui.label(f"Real book size in {'millimeters' if mm else 'inches'}, then Apply."
                     + (" (Pixels do not apply to a real book, so inches are used.)" if s.unit == "px" else "")
                     ).classes("text-xs text-gray-500")
            step, fmt = (5.0, "%.1f") if mm else (0.25, "%.2f")
            rw = ui.number(f"Real width ({name})", value=6.0 * k, step=step, format=fmt).classes("w-full")
            rh = ui.number(f"Real height ({name})", value=9.0 * k, step=step, format=fmt).classes("w-full")
            rt = ui.number(f"Real thickness ({name})", value=3.0 * k, step=step, format=fmt).classes("w-full")
            sc = ui.number("Scale 1 :", value=12, step=1, format="%.0f").classes("w-full")

            def apply_scale():
                try:
                    ctl.apply_scale(float(rw.value) / k, float(rh.value) / k, float(rt.value) / k, float(sc.value))
                except (TypeError, ValueError):
                    ui.notify("Enter all four numbers first.", type="warning")
                    return
                settings_panel.refresh()
                problems_label.refresh()
                summary_label.refresh()
                changed()
            ui.button("Apply", on_click=apply_scale).props("flat dense")

        ui.separator().classes("my-2")
        ui.label("Back cover").classes("text-sm font-semibold")

        def on_back_style(e):
            apply(back_style=e.value)
            settings_panel.refresh()
        ui.radio({"copy": "Same as the front", "complement": "Solid colour (same as the spine)",
                  "details": "Solid colour with read date and rating"},
                 value=s.back_style, on_change=on_back_style).props("dense")
        if s.back_style == "details":
            ui.switch("Show the date read", value=s.back_show_date,
                      on_change=lambda e: (apply(back_show_date=e.value), settings_panel.refresh()))
            if s.back_show_date:
                ui.select(DATE_FORMAT_CHOICES, value=s.back_date_format, label="Date shows",
                          on_change=lambda e: apply(back_date_format=e.value)).classes("w-full")
            ui.switch("Show the star rating", value=s.back_show_rating,
                      on_change=lambda e: apply(back_show_rating=e.value))
            ui.label("Books without a date or rating simply leave that part out.").classes("text-xs text-gray-500")

        ui.label("Spine text").classes("text-sm font-semibold mt-2")
        ui.switch("Hide author", value=s.spine_hide_author,
                  on_change=lambda e: apply(spine_hide_author=e.value))
        ui.switch("Drop subtitle (after the colon)", value=s.spine_drop_subtitle,
                  on_change=lambda e: apply(spine_drop_subtitle=e.value))
        ui.switch("Read bottom to top", value=s.spine_reverse,
                  on_change=lambda e: apply(spine_reverse=e.value))
        ui.number(label="Smallest text (pt)", value=s.spine_min_font_pt, step=0.5, min=2, max=12,
                  format="%.1f",
                  on_change=lambda e: e.value is not None and apply(spine_min_font_pt=float(e.value))
                  ).classes("w-full")
        ui.number(label="Largest text (pt)", value=s.spine_max_font_pt, step=0.5, min=2, max=40,
                  format="%.1f",
                  on_change=lambda e: e.value is not None and apply(spine_max_font_pt=float(e.value))
                  ).classes("w-full")
        wrap_ui["switch"] = ui.switch("Wrap long titles onto two lines", value=s.spine_wrap,
                                      on_change=lambda e: apply(spine_wrap=e.value))
        wrap_ui["hint"] = ui.label("").classes("text-xs text-gray-500")
        ui.label("Instead of cutting a long title short with “…”.").classes("text-xs text-gray-500")
        sync_wrap()

        ui.separator().classes("my-2")
        ui.label("Print sheet").classes("text-sm font-semibold")
        ui.select({"letter": "US Letter", "a4": "A4"}, value=s.paper, label="Paper",
                  on_change=lambda e: apply(paper=e.value)).classes("w-full")

        num_field("Gap between books", s.gutter_mm, "gutter_mm")
        num_field("Page margin", s.margin_mm, "margin_mm")
        ui.switch("Fold marks (short, at the spine edges)", value=s.fold_marks,
                  on_change=lambda e: apply(fold_marks=e.value))

        def on_dpi(e):
            apply(dpi=int(e.value))
            if ctl.settings.unit == "px":
                settings_panel.refresh()
        ui.select({150: "150 dpi (draft)", 300: "300 dpi", 600: "600 dpi"}, value=s.dpi, label="Print quality",
                  on_change=on_dpi).classes("w-full")

        ui.label("Settings are saved automatically.").classes("text-xs text-gray-500 mt-2")

    def key_panel():
        """Google Books key: it only affects cover search, so it lives on the Books tab and never redraws the preview."""
        ui.input(label="Google Books API key (optional)", value=ctl.settings.google_api_key, password=True,
                 password_toggle_button=True,
                 on_change=lambda e: ctl.update_settings(google_api_key=(e.value or "").strip())).classes("w-full")
        ui.label("Without a key Google often answers “429 Too Many Requests” and only Open Library is used. "
                 "A free key gives you your own allowance: in Google Cloud Console create a project, "
                 "enable the Books API, then create an API key.").classes("text-xs text-gray-500")

    # ---------- settings file (SET-04) ----------
    async def export_settings_file():
        folder, _name = ctl.save_suggestion()
        chosen = await choose_save_path(folder, "minibook-settings.json", "json")
        if not chosen:
            return
        try:
            out = _with_extension(Path(chosen), "json")
            out.write_text(ctl.export_settings(), encoding="utf-8")
        except OSError as err:
            ui.notify(f"Could not save the settings file: {err}", type="negative")
            return
        ui.notify(f"Settings saved to {out}", type="positive")

    # ---------- whole workspace (WS-*) ----------
    async def save_workspace_file():
        folder, _name = ctl.save_suggestion()
        chosen = await choose_save_path(folder, ctl.workspace_filename(), "workspace")
        if not chosen:
            return
        try:
            out = _with_extension(Path(chosen), "workspace")
            data = await run.io_bound(ctl.save_workspace)
            out.write_bytes(data)
        except OSError as err:
            ui.notify(f"Could not save the workspace: {err}", type="negative")
            return
        ui.notify(f"Workspace saved to {out}", type="positive")

    async def open_workspace_file(e):
        try:
            data, _name = await read_upload(e)
            info = await run.io_bound(ctl.open_workspace, data)
        except workspace.WorkspaceError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        except Exception as err:
            ui.notify(f"Could not read that file: {err}", type="negative")
            return
        ui.notify(f"Opened a workspace with {info['books']} books ({info['by_hand']} added by hand).", type="positive")
        settings_panel.refresh()
        problems_label.refresh()
        filter_row.refresh()
        review_list.refresh()
        summary_label.refresh()
        changed()

    async def import_settings_file(e):
        try:
            data, _name = await read_upload(e)
        except Exception as err:
            ui.notify(f"Could not read that file: {err}", type="negative")
            return
        res = ctl.import_settings(data)
        if res.settings is None:
            ui.notify("Settings not imported: " + "; ".join(res.problems), type="negative", multi_line=True)
            return
        msg = f"Imported {len(res.applied)} setting(s)."
        if res.ignored:
            msg += f" Skipped: {', '.join(res.ignored[:5])}."
        ui.notify(msg, type="warning" if res.ignored else "positive")
        settings_panel.refresh()
        problems_label.refresh()
        summary_label.refresh()
        changed()

    # ---------- one row per book (re-drawn on its own, so nothing else reloads) ----------
    def row_content(book: c.Book):
        st = ctl.state(book)
        status = ctl.status(book)
        with ui.row().classes("w-full items-center gap-3 py-1 border-b"):
            def on_check(e, bid=book.id):
                ctl.set_selected(bid, bool(e.value))
                summary_label.refresh()
                touch()
            ui.checkbox(value=book.selected, on_change=on_check)
            if st.image is not None:
                # A plain <img> loaded at once: far lighter than Quasar's image widget (which loads only what
                # is on screen and watches its size), so scrolling and opening menus stay quick.
                ui.element("img").props(f'src="{ctl.thumb_url(book)}" loading="eager" decoding="async"') \
                    .classes("w-9 h-auto rounded-sm")
            else:
                ui.element("div").classes("w-9 h-12 bg-gray-200 rounded")
            with ui.column().classes("grow gap-0"):
                ui.label(book.title).classes("font-medium")
                meta = book.author + (f"  •  {book.format}" if book.format else "")
                if book.read_date:
                    meta += f"  •  read {book.read_date}"
                if book.rating:
                    meta += f"  •  {book.rating:g} stars"
                ui.label(meta).classes("text-xs text-gray-500")
                for w in status.warnings[:2]:
                    ui.label(w).classes("text-xs text-orange-700")
                if book.duplicate:
                    ui.label("Another edition of this title is in the list").classes("text-xs text-orange-700")
            if status.quality:
                ui.badge(f"{QUALITY_TEXT[status.quality]} {status.size_text}", color=QUALITY_COLOR[status.quality])
            ui.button("Edit", icon="edit", on_click=lambda _=None, b=book: open_edit_dialog(b)).props("flat dense")
            ui.button("Cover", icon="image", on_click=lambda _=None, b=book: open_cover_dialog(b)).props("flat dense")

    def render_row(book: c.Book):
        box = row_boxes.get(book.id)
        if box is None:
            return
        box.clear()
        with box:
            row_content(book)

    # ---------- cover dialog: built once, outside every refreshable, so list updates cannot close it ----------
    def finish_cover():
        book = current["book"]
        current["book"] = None
        if book is not None:
            render_row(book)          # only this book's row
        summary_label.refresh()
        changed()                     # the preview redraws only if it is the tab being looked at

    async def open_cover_dialog(book: c.Book):
        current["book"] = book
        cover_holder.clear()
        cover_dialog.open()
        with cover_holder:
            ui.spinner(size="lg")
            ui.label("Looking for covers and other editions...")
        st = await run.io_bound(ctl.ensure_cover, book)
        if ctl.svc is not None:
            st = await run.io_bound(ctl.more_options, book)       # other editions, a looser search; once per book

        thumbs: dict[str, str] = {}

        def make_thumbs():
            from concurrent.futures import ThreadPoolExecutor

            def one(cand):
                try:
                    return cand.url, data_url(ctl.load_candidate_image(cand), 220)
                except Exception:
                    return cand.url, None
            mine = ctl.custom_candidate(book)
            todo = [x for x in ([mine] if mine else []) + list(st.candidates) if x.url not in thumbs]
            with ThreadPoolExecutor(max_workers=6) as pool:        # decode the candidates side by side
                for url, du in pool.map(one, todo):
                    if du:
                        thumbs[url] = du
        if st.candidates or ctl.custom_candidate(book) is not None:
            await run.io_bound(make_thumbs)

        def cover_cards(items, p):
            """Two columns. Click a cover to use it; its details are written underneath."""
            with ui.element("div").style(
                    "display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; width: 100%"):
                for cand in items:
                    level, dpi, lossy = ctl.candidate_info(cand)
                    mine = cand.source == "User added"
                    chosen = st.custom if mine else (p.cover_url == cand.url and not st.custom)
                    card = ui.card().classes("p-2 gap-1 cursor-pointer" + (" ring-2 ring-primary" if chosen else "")) \
                        .style("min-width: 0; align-items: stretch")
                    card.on("click", lambda _=None, x=cand: choose(x))
                    with card:
                        if cand.url in thumbs:
                            ui.image(thumbs[cand.url]).props("fit=contain").style("height: 170px")
                        else:
                            ui.element("div").style("height: 170px")
                        ui.label(cand.title or cand.label).classes("text-sm font-medium leading-tight") \
                            .style("word-break: break-word")
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.label(cand.size_text).classes("text-xs")
                            ui.badge(QUALITY_TEXT[level], color=QUALITY_COLOR[level])
                            if lossy:
                                ui.badge("crops a lot", color="orange")
                            if chosen:
                                ui.badge("Selected", color="primary")
                        if cand.why:
                            ui.label(cand.why).classes("text-xs text-orange-700")
                        if cand.note:
                            ui.label(cand.note).classes("text-xs text-orange-700")
                        ui.label(cand.source).classes("text-xs text-gray-500")

        @ui.refreshable
        def body():
            p = ctl.book_prefs(book)
            ui.label(f"{book.title}  —  {book.author}").classes("text-lg font-bold")
            if book.is_audio:
                ui.label("Audiobook: square art gets cropped. Look for a print cover, or upload your own.") \
                    .classes("text-sm text-orange-700")
            # the row takes whatever height is left between the title and the Done button, and each side
            # looks after its own overflow, so nothing needs the whole window to scroll
            with ui.row().classes("w-full gap-6 no-wrap").style("flex: 1 1 0; min-height: 0"):
                with ui.column().classes("gap-2").style("flex: 1 1 0; min-width: 0; height: 100%"):
                    ui.label(f"Choose a cover ({len(covers.likely(st.candidates)) + (1 if ctl.custom_candidate(book) else 0)})").classes("font-semibold")
                    shown = covers.likely(st.candidates)
                    mine = ctl.custom_candidate(book)
                    if mine is not None:
                        shown = [mine] + list(shown)
                    if shown:
                        if all(x.source != "User added" for x in shown) and shown[0].tier != covers.TIER_GOOD:
                            ui.label("No close match found. These are the nearest results:").classes("text-sm text-orange-700")
                        with ui.column().classes("w-full gap-2").style(
                                "flex: 1 1 0; min-height: 0; overflow-y: auto; padding-right: 8px"):
                            cover_cards(shown, p)
                    else:
                        ui.label("No covers found online." + (f" ({'; '.join(st.errors[:2])})" if st.errors else "")) \
                            .classes("text-sm text-gray-600")
                with ui.column().classes("gap-1").style("width: 330px; flex: none; height: 100%; overflow: hidden; padding: 0 12px"):
                    ui.label("Crop").classes("font-semibold")
                    if st.image is None:
                        ui.label("Pick a cover to see the crop.").classes("text-sm text-gray-600")
                    else:
                        prev = ctl.crop_preview(book)
                        crop_img = ui.image(data_url(prev, fmt="PNG")).props("fit=contain").classes("w-full border") \
                            .style("height: 19vh")
                        net_img = ui.image(data_url(ctl.net_for(book).image, 700, "PNG")).props("fit=contain") \
                            .classes("w-full border").style("height: 11vh")

                        def on_crop(**kw):
                            ctl.set_crop(book, **kw)
                            crop_img.set_source(data_url(ctl.crop_preview(book), fmt="PNG"))
                            net_img.set_source(data_url(ctl.net_for(book).image, 700, "PNG"))
                            color_grid.refresh()

                        @ui.refreshable
                        def color_grid():
                            """Spine and back color: Auto, black, white, then the cover's own top colors (3 x 3)."""
                            ov = ctl.spine_override(book)
                            cur = imaging.to_hex(ov) if ov else None
                            auto = ctl.auto_color(book) or (128, 128, 128)
                            opts = [(None, auto, "Auto"), ("#000000", (0, 0, 0), "Black"), ("#ffffff", (255, 255, 255), "White")]
                            opts += [(imaging.to_hex(rgb), rgb, "Cover color") for rgb in ctl.cover_palette(book)[:6]]
                            ui.label("Spine and back color").classes("text-xs")
                            with ui.element("div").style(
                                    "display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; width: 100%"):
                                for hexv, rgb, name in opts:
                                    on = (cur or None) == hexv
                                    sw = ui.element("div").classes("cursor-pointer rounded border" + (" ring-2 ring-primary" if on else "")) \
                                        .style(f"background: {imaging.to_hex(rgb)}; height: 30px; display: flex; "
                                               f"align-items: center; justify-content: center; font-size: 12px; "
                                               f"color: {'#000' if sum(rgb) > 380 else '#fff'}")
                                    sw.on("click", lambda _=None, h=hexv: pick_color(h))
                                    with sw:
                                        if name == "Auto":
                                            ui.label("Auto")
                                        ui.tooltip(name)

                        def pick_color(hexv):
                            ctl.set_spine_color(book, imaging.from_hex(hexv))
                            net_img.set_source(data_url(ctl.net_for(book).image, 700, "PNG"))
                            color_grid.refresh()
                        color_grid()
                        zmin = ctl.zoom_min(book)
                        ui.label("Zoom (drag left to show the whole image)").classes("text-xs")
                        ui.slider(min=round(zmin, 3), max=MAX_ZOOM, step=0.01, value=max(p.zoom, zmin),
                                  on_change=lambda e: on_crop(zoom=e.value))
                        ui.label("Left ↔ right").classes("text-xs")
                        ui.slider(min=0.0, max=1.0, step=0.01, value=p.pan_x,
                                  on_change=lambda e: on_crop(pan_x=e.value))
                        ui.label("Up ↕ down").classes("text-xs")
                        ui.slider(min=0.0, max=1.0, step=0.01, value=p.pan_y,
                                  on_change=lambda e: on_crop(pan_y=e.value))

                        def reset():
                            ctl.reset_crop(book)
                            body.refresh()
                        ui.button("Reset crop", on_click=reset).props("flat dense")
            with ui.row().classes("w-full justify-between no-wrap").style("flex: none; align-items: flex-end"):
                with ui.column().classes("gap-0").style("flex: 1 1 0; min-width: 0"):
                    ui.label("Or use your own image").classes("font-semibold")

                    async def on_upload(e):
                        try:
                            data, _name = await read_upload(e)
                            ctl.set_custom_image(book, data)
                        except covers.CoverError as err:
                            ui.notify(str(err), type="negative")
                            return
                        mine = ctl.custom_candidate(book)
                        if mine is not None:
                            thumbs.pop(mine.url, None)
                            await run.io_bound(make_thumbs)
                        ui.notify("Your image is added to the covers above.", type="positive")
                        body.refresh()
                    ui.upload(label="Drop a JPG or PNG here", auto_upload=True, on_upload=on_upload,
                              max_files=1).props("accept=image/* flat dense").classes("w-full").style(
                                  "min-height: 0; max-height: 64px; overflow: hidden")
                ui.button("Done", on_click=cover_dialog.close).props("color=primary")

        def choose(cand):
            try:
                if cand.source == "User added":
                    ctl.use_custom_image(book)
                else:
                    ctl.choose_candidate(book, cand)
            except covers.CoverError as err:
                ui.notify(str(err), type="negative")
                return
            body.refresh()

        cover_holder.clear()
        with cover_holder:
            body()

    # ---------- edit dialog (also built once) ----------
    def open_edit_dialog(book: c.Book):
        edit_holder.clear()
        with edit_holder:
            ui.label("Edit book").classes("text-lg font-bold")
            t = ui.input(label="Title", value=book.title).classes("w-full")
            a = ui.input(label="Author (separate several with commas)", value=book.author).classes("w-full")
            i = ui.input(label="ISBN", value=book.isbn or book.asin or "").classes("w-full")
            with ui.row().classes("w-full gap-2 no-wrap"):
                d = ui.input(label="Date read (2024, 2024-05 or 2024-05-17)",
                             value=str(book.read_date) if book.read_date else "").classes("grow")
                rt = ui.number(label="Star rating (0.25 to 5)", value=book.rating, min=0, max=5, step=0.25,
                               format="%.2f").props("clearable").classes("w-40")
            ui.label("Changing the title, author or ISBN searches for the cover again. "
                     "The date and rating are used on the back cover and for the year filter.") \
                .classes("text-xs text-gray-500")

            def save():
                before = [id(x) for x in ctl.visible()]
                old_id = book.id
                try:
                    ctl.edit_book(book, t.value or "", a.value or "", i.value or "",
                                  read_date=d.value or "", rating=rt.value)
                except ValueError as err:
                    ui.notify(str(err), type="negative")
                    return
                edit_dialog.close()
                box = row_boxes.pop(old_id, None)
                if box is not None and before == [id(x) for x in ctl.visible()]:
                    row_boxes[book.id] = box          # same place in the list: redraw only this row
                    render_row(book)
                else:
                    review_list.refresh()             # the order changed, so the list has to be redrawn
                filter_row.refresh()                  # a new date can add or remove a year
                summary_label.refresh()
                touch()
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=edit_dialog.close).props("flat")
                ui.button("Save", icon="save", on_click=save).props("color=primary")
        edit_dialog.open()

    # ---------- review list ----------
    @ui.refreshable
    def review_list():
        row_boxes.clear()
        groups = []
        if ctl.manual:
            groups.append(("Added by hand", "manual", ctl.manual))
        if ctl.all_books:
            label = f"Read in {ctl.year}" if ctl.year else "Matching books"
            groups.append((label, "dated", ctl.dated))
            if ctl.undated:
                state = "checked" if ctl.year is None else "unchecked"
                groups.append((f"No read date ({len(ctl.undated)}) — {state}", "undated", ctl.undated))
        if not groups:
            ui.label("Upload your StoryGraph or Goodreads export, or add a book by hand to begin.").classes("text-gray-500")
            return
        for title, key, books in groups:
            with ui.row().classes("w-full items-center justify-between mt-2"):
                ui.label(title).classes("font-semibold")
                with ui.row().classes("gap-1"):
                    def set_group(value, k=key):
                        ctl.select_all(value, k)
                        review_list.refresh()
                        summary_label.refresh()
                        touch()
                    ui.button("All", on_click=lambda _=None, f=set_group: f(True)).props("flat dense")
                    ui.button("None", on_click=lambda _=None, f=set_group: f(False)).props("flat dense")
            if not books:
                ui.label("Nothing here.").classes("text-sm text-gray-500")
            for b in books:
                # content-visibility lets the browser skip laying out rows that are off screen
                box = ui.column().classes("w-full gap-0").style(
                    "content-visibility: auto; contain-intrinsic-size: auto 56px")
                row_boxes[b.id] = box
                with box:
                    row_content(b)

    # ---------- import card ----------
    @ui.refreshable
    def filter_row():
        if not ctl.all_books:
            return
        years = c.available_years(ctl.all_books)
        with ui.row().classes("items-center gap-4"):
            def refilter(*_):
                ctl.filter_from_choices(year_sel.value, list(status_sel.value or []))
                review_list.refresh()
                summary_label.refresh()
                touch()
            year_options = {YEAR_ALL: "All years", **{y: str(y) for y in years}}
            year_sel = ui.select(year_options, value=ctl.year_choice() if ctl.year_choice() in year_options else YEAR_ALL,
                                 label="Year read", on_change=refilter).props("options-dense behavior=menu").classes("w-36")
            status_sel = ui.select(STATUS_OPTIONS, value=ctl.status_choices(), multiple=True,
                                   label="Status", on_change=refilter).props("options-dense behavior=menu").classes("w-72")

    async def on_csv(e):
        try:
            data, name = await read_upload(e)
            info = ctl.load_csv(data, name)
        except c.CsvFormatError as err:
            ui.notify(str(err), type="negative", multi_line=True)
            return
        except Exception as err:  # unreadable bytes, odd encodings...
            ui.notify(f"Could not read that file: {err}", type="negative")
            return
        ui.notify(f"Loaded {info['books']} books.", type="positive")
        filter_row.refresh()
        review_list.refresh()
        summary_label.refresh()
        touch()

    def add_manual():
        try:
            ctl.add_manual(m_title.value or "", m_author.value or "", m_isbn.value or "",
                           m_date.value or "", m_rating.value)
        except ValueError as err:
            ui.notify(str(err), type="warning")
            return
        m_title.value = m_author.value = m_isbn.value = m_date.value = ""
        m_rating.value = None
        review_list.refresh()
        summary_label.refresh()
        touch()

    # ---------- export ----------
    result_box = None
    fetch_prog = None
    make_prog = None

    async def fetch_all():
        await fetch_books(ctl.selected_books(), "Nothing is selected.")

    async def fetch_edited():
        await fetch_books(ctl.edited_books(), "No books have been edited since their cover was looked up.")

    async def fetch_books(books, empty_message):
        if not books:
            ui.notify(empty_message, type="warning")
            return
        if ctl.svc is None:
            ui.notify("Cover lookup is switched off (offline mode).", type="warning")
            return
        todo = [b for b in books if ctl.needs_cover(b)]     # covers already found are left alone
        await run_with_progress("Fetching covers", lambda cb: [
            (ctl.ensure_cover(b), cb(i, len(todo), b.title)) for i, b in enumerate(todo, 1)], fetch_prog)
        for b in todo:                # redraw only the rows that changed
            render_row(b)
        touch()
        missing = sum(1 for b in books if not ctl.status(b).has_cover)
        ui.notify(f"Covers ready. {missing} book(s) have none: use the Cover button to add your own.",
                  type="warning" if missing else "positive")
        for note in ctl.svc.notices:
            ui.notify(note, type="warning", multi_line=True)

    def make_progress() -> dict:
        bar = ui.linear_progress(value=0, show_value=False).classes("w-full")
        bar.set_visibility(False)
        return {"bar": bar, "label": ui.label("").classes("text-xs text-gray-600")}

    async def run_with_progress(label: str, work, prog: dict):
        progress_state.update(i=0, n=1, title="", busy=True, target=prog)
        bar, status_lbl = prog["bar"], prog["label"]
        bar.set_visibility(True)
        status_lbl.set_text(label + "...")
        timer.activate()

        def cb(i, n, title):
            progress_state.update(i=i, n=n, title=title)
        try:
            return await run.io_bound(work, cb)
        finally:
            progress_state["busy"] = False
            timer.deactivate()
            bar.set_value(1.0)
            status_lbl.set_text("")
            bar.set_visibility(False)

    def tick():
        prog = progress_state.get("target")
        if prog is None:
            return
        n = max(1, progress_state["n"])
        prog["bar"].set_value(progress_state["i"] / n)
        prog["label"].set_text(f"{progress_state['i']}/{n}  {progress_state['title']}")

    async def make_pdf():
        problems = ctl.settings.validate()
        if problems:
            ui.notify("Fix the settings first: " + problems[0], type="negative")
            return
        if not ctl.selected_books():
            ui.notify("No books are selected.", type="warning")
            return
        folder, name = ctl.save_suggestion()
        chosen = await choose_save_path(folder, name)       # module-level so it can be swapped in tests
        if not chosen:
            return                                          # cancelled: nothing is built
        out = pdf_path(chosen)
        try:
            path, nets, pages = await run_with_progress("Building PDF", lambda cb: ctl.export(cb, out_path=out), make_prog)
        except Exception as err:
            ui.notify(f"Could not create the PDF: {err}", type="negative", multi_line=True)
            return
        ctl.remember_save_location(path)
        flagged = [n for n in nets if n.warnings]
        result_box.clear()
        with result_box:
            ui.label(f"Saved {path.name}: {len(nets)} books on {pages} page(s).").classes("font-semibold")
            ui.label(str(path)).classes("text-xs text-gray-600 break-all")
            if flagged:
                ui.label(f"{len(flagged)} book(s) need a look:").classes("text-sm text-orange-700 mt-1")
                for n in flagged[:12]:
                    ui.label(f"• {n.book.title}: {'; '.join(n.warnings[:2])}").classes("text-xs")
                if len(flagged) > 12:
                    ui.label(f"...and {len(flagged) - 12} more").classes("text-xs")
        for b in ctl.selected_books():
            render_row(b)
        ui.notify("PDF saved.", type="positive")

    async def make_svg():
        problems = ctl.settings.validate()
        if problems:
            ui.notify("Fix the settings first: " + problems[0], type="negative")
            return
        if not ctl.selected_books():
            ui.notify("No books are selected.", type="warning")
            return
        folder, _name = ctl.save_suggestion()
        chosen = await choose_save_path(folder, ctl.default_svg_filename(), "svg")
        if not chosen:
            return
        out = _with_extension(Path(chosen), "svg")
        try:
            paths, nets, pages = await run_with_progress("Building SVG", lambda cb: ctl.export_svg(cb, out_path=out), make_prog)
        except Exception as err:
            ui.notify(f"Could not create the SVG: {err}", type="negative", multi_line=True)
            return
        ctl.remember_save_location(paths[0])
        result_box.clear()
        with result_box:
            ui.label(f"Saved {len(nets)} books on {pages} SVG page(s).").classes("font-semibold")
            for pth in paths[:6]:
                ui.label(str(pth)).classes("text-xs text-gray-600 break-all")
            if len(paths) > 6:
                ui.label(f"...and {len(paths) - 6} more").classes("text-xs")
        ui.notify("SVG saved.", type="positive")

    async def make_test_print():
        problems = ctl.settings.validate()
        if problems:
            ui.notify("Fix the settings first: " + problems[0], type="negative")
            return
        folder, _name = ctl.save_suggestion()
        chosen = await choose_save_path(folder, "minibook_test_print.pdf")
        if not chosen:
            return
        out = pdf_path(chosen)
        try:
            path, info = await run.io_bound(ctl.export_test_print, out)
        except Exception as err:
            ui.notify(f"Could not create the test print: {err}", type="negative", multi_line=True)
            return
        ctl.remember_save_location(path)
        result_box.clear()
        with result_box:
            ui.label(f"Saved the test print {path.name}.").classes("font-semibold")
            ui.label(str(path)).classes("text-xs text-gray-600 break-all")
            ui.label("Print it at 100% (actual size) and check the ruler with a real ruler.").classes("text-xs")
            for n in info.notes:
                ui.label(n).classes("text-xs text-orange-700")
        ui.notify("Test print saved.", type="positive")

    # ---------- layout ----------
    with ui.header().classes("items-center justify-between"):
        ui.label(APP_TITLE).classes("text-lg font-bold")
        with ui.tabs().props("dense indicator-color=white") as tabs:
            ui.tab("books", label="Books", icon="menu_book")
            ui.tab("preview", label="Preview", icon="grid_view")
        ui.label("Wraps for mini books").classes("text-sm opacity-80")

    with ui.tab_panels(tabs, value="books", animated=False, keep_alive=True, on_change=on_tab).classes("w-full"):
        # ----- Books tab: choose and tidy the books, look up covers -----
        with ui.tab_panel("books"):
            with ui.column().classes("w-full max-w-4xl mx-auto gap-4"):
                with ui.card().classes("w-full"):
                    ui.label("1. Choose your books").classes("text-lg font-bold")
                    ui.upload(label="Drop your StoryGraph or Goodreads CSV here", auto_upload=True, on_upload=on_csv,
                              max_files=1).props("accept=.csv").classes("w-full")
                    with ui.row().classes("w-full items-center gap-3"):
                        ui.label("Or open a saved workspace:").classes("text-sm")
                        ui.upload(label="Open workspace", auto_upload=True, on_upload=open_workspace_file,
                                  max_files=1).props("accept=.minibook flat dense").classes("grow")
                    filter_row()
                    with ui.expansion("Add a book by hand", icon="edit").classes("w-full"):
                        with ui.row().classes("items-end gap-2"):
                            m_title = ui.input(label="Title").classes("w-64")
                            m_author = ui.input(label="Author").classes("w-48")
                            m_isbn = ui.input(label="ISBN (optional)").classes("w-40")
                            m_date = ui.input(label="Date read (optional)", placeholder="2024-05-17").classes("w-40")
                            m_rating = ui.number(label="Stars (optional)", min=0, max=5, step=0.25,
                                                 format="%.2f").props("clearable").classes("w-28")
                            ui.button("Add", icon="add", on_click=add_manual)
                    with ui.expansion("Cover search key (Google Books)", icon="key").classes("w-full"):
                        key_panel()
                    with ui.row().classes("items-center gap-3"):
                        ui.button("Fetch covers", icon="cloud_download", on_click=fetch_all).props("outline")
                        ui.button("Fetch edited only", icon="sync", on_click=fetch_edited).props("outline")
                        ui.space()
                        ui.button("Save workspace", icon="save", on_click=save_workspace_file).props("outline")
                    fetch_prog = make_progress()

                with ui.card().classes("w-full"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("2. Check covers and pick the books").classes("text-lg font-bold")
                        summary_label()
                    review_list()

        # ----- Preview tab: output settings on the left, the live print sheet on the right -----
        with ui.tab_panel("preview").style("padding: 0"):
            # two independent scrolling panes side by side; the page itself does not scroll here
            with ui.row().classes("w-full no-wrap items-stretch gap-0").style(
                    "height: calc(100vh - 110px); overflow: hidden").classes("mb-preview-row"):
                with ui.column().classes("w-80 shrink-0 gap-1").style(
                        "height: 100%; overflow-y: auto; padding: 12px; border-right: 1px solid #d0d0d0"):
                    ui.label("Settings").classes("text-lg font-bold")
                    settings_panel()
                    problems_label()
                    ui.separator().classes("my-2")
                    ui.label("Settings file").classes("text-sm font-semibold")
                    ui.label("Save these settings to reuse later or share. The Google key and your "
                             "books are not included.").classes("text-xs text-gray-500")
                    ui.button("Export settings", icon="upload_file", on_click=export_settings_file).props("flat dense")
                    ui.upload(label="Import settings", auto_upload=True, on_upload=import_settings_file,
                              max_files=1).props("accept=.json").classes("w-full")
                with ui.column().classes("grow gap-2 items-start").style(
                        "height: 100%; overflow: auto; padding: 12px; min-width: 0"):
                    with ui.row().classes("w-full items-center gap-3"):
                        pv_ui["prev"] = ui.button(icon="chevron_left", on_click=lambda: go_page(-1)).props("flat dense")
                        pv_ui["page_label"] = ui.label("Page 1").classes("font-semibold")
                        pv_ui["next"] = ui.button(icon="chevron_right", on_click=lambda: go_page(1)).props("flat dense")
                        pv_ui["busy"] = ui.label("").classes("text-xs text-gray-500")
                        ui.space()
                        ui.button("Test print", icon="straighten", on_click=make_test_print).props("flat dense")
                        ui.button("Create SVG", icon="draw", on_click=make_svg).props("outline dense")
                        ui.button("Create PDF", icon="picture_as_pdf", on_click=make_pdf).props("color=primary")
                    make_prog = make_progress()
                    result_box = ui.column().classes("w-full gap-1")
                    pv_ui["stats"] = ui.label("").classes("text-xs text-gray-500")
                    pv_ui["note"] = ui.label("").classes("text-gray-600")
                    pv_ui["error"] = ui.label("").classes("text-red-600")
                    pv_ui["image"] = ui.interactive_image(BLANK_IMAGE, on_mouse=on_preview_click, events=["click"],
                                                          cross=False).classes("border shadow-sm")
                    pv_ui["image"].set_visibility(False)

    # zoom bar along the bottom of the window, shown only on the Preview tab
    pv_ui["footer"] = ui.footer(value=False, fixed=True).classes("bg-white text-black").props("bordered")
    with pv_ui["footer"]:
        with ui.row().classes("w-full items-center justify-center gap-3 no-wrap"):
            ui.icon("zoom_out")
            pv_ui["slider"] = ui.slider(min=25, max=300, step=5, value=100,
                                        on_change=lambda e: set_zoom(e.value / 100)).classes("w-96")
            ui.icon("zoom_in")
            pv_ui["zoom_label"] = ui.label("100%").classes("w-12 text-sm")
            ui.button("100%", on_click=lambda: set_zoom(1.0)).props("flat dense")

    timer = ui.timer(0.25, tick, active=False)
    pv_ui["timer"] = ui.timer(0.1, poll_preview, active=False)

    # dialogs live at page level, never inside a refreshable
    cover_dialog = ui.dialog()
    # a fixed-height card (so the Done button is always in view) that overrides Quasar's 560 px dialog limit
    with cover_dialog, ui.card().style(
            "max-width: none; width: min(1100px, 96vw); height: min(92vh, 900px); overflow: hidden"):
        cover_holder = ui.column().classes("w-full gap-2 no-wrap").style("height: 100%")
    cover_dialog.on_value_change(lambda e: finish_cover() if not e.value else None)
    edit_dialog = ui.dialog()
    with edit_dialog, ui.card().classes("w-[min(520px,95vw)]"):
        edit_holder = ui.column().classes("w-full")


# -- entry point ------------------------------------------------------------------------------------
def make_controller(offline: bool = False) -> AppController:
    settings = S.load_settings()
    prefs = S.load_book_prefs()
    svc = None if offline else covers.CoverService(covers.RequestsHttp(), S.cache_dir() / "covers")
    return AppController(settings, prefs, svc)      # the controller hands the saved Google key to the service


def _pywebview_available() -> bool:
    """True only if a window can really open. On Linux pywebview also needs a Qt or GTK backend;
    having `webview` alone makes the window crash on start."""
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    if not sys.platform.startswith("linux"):
        return True
    for backend in ("qtpy", "gi"):
        try:
            __import__(backend)
            return True
        except Exception:
            continue
    return False


def thumb_payload(ctl: AppController, book_id: str) -> bytes | None:
    return ctl.thumb_bytes(book_id)


def register_routes(ctl: AppController) -> None:
    """Serve the small list images by URL. The URL changes whenever a cover changes, so the browser
    can keep them for good: scrolling and redrawing the list then never re-sends or re-decodes them."""
    from nicegui import app

    @app.get("/thumb/{book_id}")
    def thumb(book_id: str):
        from fastapi import Response
        data = thumb_payload(ctl, book_id)
        if data is None:
            return Response(status_code=404)
        return Response(content=data, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


def main(argv: list[str] | None = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="minibook_gui")
    ap.add_argument("--browser", action="store_true", help="open in your web browser instead of a window")
    ap.add_argument("--offline", action="store_true", help="no cover lookup")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)

    ctl = make_controller(args.offline)
    register_routes(ctl)

    @ui.page("/")
    def index():
        build_page(ctl)

    global NATIVE
    native = (not args.browser) and _pywebview_available()
    NATIVE = native
    if not args.browser and not native:
        print("No window backend is installed, so opening in your web browser instead. "
              'For a standalone window: pip install "pywebview[qt]"')
    kwargs = dict(title=APP_TITLE, reload=False, show=not native, native=native)
    if native:
        kwargs["window_size"] = (1360, 900)      # NiceGUI picks a free port itself in native mode
    else:
        kwargs["port"] = args.port
    ui.run(**kwargs)
