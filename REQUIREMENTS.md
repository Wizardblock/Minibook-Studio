# MiniBook Studio: Requirements

Turns a StoryGraph CSV (or typed titles) into a printable PDF of wraps for mini books
made from same-size foam core boards. Every requirement has an ID. Every test in
`tests/` names the IDs it covers, so the code can be checked against this file.

**Phases:** `P1` = first build, `P2` = second build, `P3` = after everything works.

## Confirmed decisions

| Topic | Decision |
|---|---|
| Net | Back, spine, front only. No tabs, no outlines. Cut marks only. |
| Back cover | Identical copy of the front (not mirrored, not blurred) or a solid color matching the spine. |
| Board size | Height and width, or height and aspect ratio. Thickness sets the spine. |
| Default size | 1.25" tall x 0.75" wide x 0.25" thick (see assumption A1). |
| Cropping | Center crop by default, manual crop per book. |
| Attach | Glue or sticker paper (Avery 53202, full 8.5 x 11 sheet): the same layout; a page-margin setting with a hint covers the difference. |
| Output | PDF only, Letter or A4. |
| Volume | About 50 books per run. |
| Settings | Saved between sessions. |
| Platform | Windows and Linux, Python 3.12, NiceGUI standalone window, packaged to an executable last. |

## Assumptions to confirm

- **A1.** The default board is **1.25" tall x 0.75" wide x 0.25" thick** (you set this; it replaced
  my earlier 0.75" x 0.5" guess). All three numbers are editable, and a scale calculator fills
  them from any real book size at 1:12 or another scale.

## Corrections to the earlier AI plan

- Page count is not in the StoryGraph export, and the spine does not use it. Spine = board thickness.
- Series auto-detection is dropped: only 1 of 157 titles has a series marker. Replaced by DATA-07.
- Streamlit caching is replaced by a local disk cache (IMG-02).
- The blur and mirror back-cover options are dropped (NET-02).
- The Avery preset list is dropped. Avery 53202 is one full blank sheet, not a label grid (EXP-04).
- Invented user reviews were brainstorming, not evidence.

## Verification status (what has and has not been checked)

| Area | How it was checked | Confidence |
|---|---|---|
| Engine: CSV, crop, spine, net, layout, PDF, settings, fold marks, zoom-out, wrapping, edits | automated tests, including measurements of the output PDF and deliberate-breakage checks | High |
| GUI logic (`controller.py`): import, selection, covers, crop, settings, export, edits | automated tests run without a window | High |
| GUI view (`gui.py`): our handlers and wiring | tests against a **stand-in** for NiceGUI (555 tests in all) | Medium: proves our code runs, not that NiceGUI's real API accepts it |
| Calls to NiceGUI | Checked by hand against the NiceGUI 3.x docs (upload events, `ui.download`, `ui.run`) | Medium |
| Open Library | You ran `check-covers`: covers loaded | Confirmed on your machine |
| Google Books | You saw HTTP 429 (quota). Handling is tested with stand-ins; a real key is untested | Unverified with a key |
| Real window | You launched it on Linux and made a PDF. The new Save As dialog, Edit dialog, px unit and zoom-out have **not** been run in a real window | Unverified for this round |

## SYS: System

| ID | Phase | Requirement |
|---|---|---|
| SYS-01 | P1 | Runs on Windows and Linux with no OS-specific code paths in the engine. Python 3.12 compatible (no 3.13-only features). |
| SYS-02 | P1 | The engine (CSV, covers, net, layout, PDF) has no GUI dependency and runs from a command line. |
| SYS-03 | P1 | GUI is NiceGUI 3.x in a native window (pywebview), with browser mode as a fallback. All GUI logic lives in `controller.py`, so the view stays thin. |
| SYS-04 | P1 | Image work uses Pillow. PDF output uses ReportLab. |
| SYS-05 | P1 | Only cover fetching uses the network. Everything else works offline. |
| SYS-06 | P3 | Packaged as a single executable per OS (built on each OS). |

## DIM: Dimensions

| ID | Phase | Requirement |
|---|---|---|
| DIM-01 | P1 | Board size is entered as height + width, or as height + aspect ratio (`0.667` or `2:3`). |
| DIM-02 | P1 | Spine width equals board thickness, entered by the user. Default 0.25". |
| DIM-03 | P1 | Units are inches, mm or pixels, switchable. Stored internally in mm. |
| DIM-03b | P1 | Pixels are pixels at the chosen print DPI (300 dpi: 1.25" = 375 px), so a cover image's pixel size can be typed straight in. |
| DIM-04 | P1 | Scale calculator: real book size + scale (default 1:12) produces board height and width. |
| DIM-05 | P1 | Render at 300 DPI by default. |
| DIM-06 | P1 | Physical sizes in the PDF are exact: the net is `2 x width + thickness` wide and `height` tall, to within 0.01 pt. |

## DATA: Input

| ID | Phase | Requirement |
|---|---|---|
| DATA-01 | P1 | Parses the StoryGraph export using its real columns: Title, Authors, ISBN/UID, Format, Read Status, Last Date Read, Dates Read, Star Rating, Review. Handles a BOM and quoted fields. |
| DATA-02 | P1 | Default filter is `Read Status = read`. Status is selectable. Year filter uses the year of the read date. |
| DATA-02b | P1 | The year box has an **All years** choice and the status box has **All statuses** (including books with no status). |
| DATA-03 | P1 | Read date comes from `Last Date Read`. If blank, falls back to the end of `Dates Read`. Accepts `YYYY/MM/DD`, `YYYY/MM`, `YYYY`, and `YYYY-` (trailing dash). |
| DATA-04 | P1 | Books with no usable date appear in an **Undated** group, unchecked by default, and can be selected. |
| DATA-05 | P1 | Review list with a checkbox per book (checked by default for dated matches). Select all / none. |
| DATA-06 | P1 | Manual entry: title, author, optional ISBN. |
| DATA-07 | P1 | Sort by author (last name), then date read, then title. Also sortable by title or date. |
| DATA-07b | — | ~~Drag to reorder.~~ **Dropped by you:** you will not use it. Print order stays author, title or date (DATA-07). |
| DATA-08 | P1 | Cleaning: trim whitespace, split multiple authors, strip HTML and `&nbsp;` from reviews, normalize ISBN-10 to ISBN-13, treat `B0...` IDs as non-ISBN, treat blank ratings as none. |
| DATA-09 | P1 | Duplicate titles in the selection are flagged (e.g. two editions of the same book). |
| DATA-10b | P1 | **Fetch edited only** looks up covers just for books edited since their last lookup. **Fetch covers** also skips books that already have one. |
| DATA-10 | P1 | Every book, from the CSV or added by hand, has an **Edit** button for title, author and ISBN. Edits to CSV books are remembered when the same file is imported again. A custom image follows the edited book; an online cover choice is cleared and searched again. |

## IMG: Covers

| ID | Phase | Requirement |
|---|---|---|
| IMG-01 | P1 | Looks up covers on Open Library, then Google Books: by ISBN first, then title + author. |
| IMG-01d | P1 | Entering or changing the Google key makes books looked up earlier be searched again on the next fetch (no restart). Chosen covers, custom images and crops are kept. |
| IMG-01c | P1 | Google Books answering 429 (quota) or a key error is reported once, with how to fix it, and Google is then left alone for the session. An optional free API key (Settings) gives its own quota; entering one retries Google. The command line uses the saved key. |
| IMG-02 | P1 | Searches and downloaded images are cached on disk. A repeat run makes no network calls. |
| IMG-03 | P1 | Audiobook entries search by title + author first. The ISBN match is listed last and labelled as possible audiobook art. |
| IMG-03b | P1 | The default pick is the best candidate, not just the first: sharp enough for the print size, an ISBN match, an exact title match, and not square audiobook art. You can always choose another. |
| IMG-04 | P1 | Picker shows all candidates with pixel size and source. |
| IMG-11 | P2 | Every result is graded: **good** (the title matches, ignoring subtitles, series notes and articles, and the author's last name matches or is not given; or found by the book's own ISBN), **possible** (title only partly matches, or a different author is listed) or **probably not** (a different title). A sequel is not a match. |
| IMG-12 | P2 | Box sets, omnibuses, bundles, study guides and summaries are recognised from the result's title, subtitle and category and graded *probably not*, unless the book itself is called that. Results are ordered good, possible, probably not. **The picker shows only the good matches** (the possible ones only when there is no good one, under a "nearest results" notice); box sets, guides and other titles are never shown or downloaded. The default cover is never a *probably not*; a *possible* one is used only when nothing better exists and the row says it is unsure; if there is no good or possible result nothing is picked and the row says to open Cover. |
| IMG-13 | P2 | More sources: Amazon's picture for the ISBN-10 or ASIN (confirmed working by you), and searches built from the title without its series note and the author's last name. |
| IMG-14 | P2 | The Google query is `intitle:"title" inauthor:"lastname"`; the Open Library search uses the title without a series note. |
| IMG-15 | P2 | **More options:** opening the picker also adds other editions of the matching work from Open Library (up to 30 covers). No extra Google request is made, to spare the quota. This was the biggest improvement in your checks. Done once per book and cached. A bulk Fetch covers downloads only the first few promising candidates per book; the picker downloads the rest, drops dead links and identical pictures, and shows sizes. The picker lists covers in two columns with the details written under each picture. **Click a cover to use it** (no button); the chosen one is marked Selected. The picker window has a fixed height with the list and the crop side scrolling on their own, so the crop controls and Done are always in view. |
| IMG-05 | P1 | Quality badge compares the cover with the actual print size: effective DPI = cropped source pixels / board width in inches. Good >= 100% of target DPI, OK >= 67%, Low below. |
| IMG-06 | P1 | Crop-loss warning when the center crop would discard more than 25% of the image (typical for square audiobook art). |
| IMG-07 | P1 | Custom image upload (JPG/PNG). |
| IMG-08 | P1 | Center crop to the board aspect ratio by default. |
| IMG-09 | P1 | Manual crop per book: zoom and pan, aspect locked, choice remembered. |
| IMG-09b | P1 | Zoom can go out until the whole image is visible. Any empty area of the front cover is filled with the spine colour, exactly. The center-crop warning only applies at the default zoom. |
| IMG-10 | P1 | Network failures are reported per book and never stop the run. A book with no cover gets a placeholder and a warning. |

## NET: Book net

Each book is one flat piece: `[ back ][ spine ][ front ]`, height = board height.

| ID | Phase | Requirement |
|---|---|---|
| NET-01 | P1 | Front and back are each board width x board height. Spine is thickness x board height. |
| NET-02 | P1 | Back cover options: identical copy of the front (default), or a solid color. **Changed after your review:** the solid color is exactly the spine color (it was a complementary color at first). |
| NET-03 | P1 | Spine background is the front cover's dominant color. Text color is chosen for contrast. |
| NET-03b | P2 | A mostly dark cover (half or more of it near-black, with a bright title) gets a near-black spine and solid back: the spine color is the average of the dark pixels, not the blended cluster color, which came out as a washed brown or grey. Applies only when the usual pick is clearly brighter than the dark pixels; checked on 28 of your covers: 6 changed (the black ones), 22 unchanged. |
| NET-04 | P1 | Spine text runs vertically (top to bottom, optional reverse), title plus author, centered. |
| NET-05 | P1 | Spine text fits automatically: author shrinks first, then is dropped, then the title shrinks, then the subtitle (after `:`) is dropped, then the title wraps onto two lines (if that setting is on and the spine is thick enough) or is truncated with an ellipsis. Never overflows. |
| NET-05a | P1 | A **largest text** size sits next to the smallest. The spine's own width can still force text smaller. |
| NET-05b | P1 | Option to wrap a title that would otherwise be truncated onto two lines, at the largest size at which two lines fit. Offered only when the spine is thick enough for two lines at the smallest size. Off by default. |
| NET-06 | P1 | Options: hide author, drop subtitle, minimum font size. A book whose text hits the minimum or is truncated is flagged. |
| NET-07 | P2 | **Delivered.** Third back-cover choice, "Solid colour with read date and rating": the spine colour plus the date read (day-month-year, month-year or year only) and the star rating as five outlined stars filled to the rating (quarter steps). Date and rating can each be shown or hidden. Missing dates or ratings are skipped. A review quote was not built. |

## EXP: Print sheet

| ID | Phase | Requirement |
|---|---|---|
| EXP-01 | P1 | PDF only. Letter or A4. |
| EXP-02 | P1 | Adjustable gutter between nets, with a minimum of 3 mm so marks never collide. |
| EXP-03 | P1 | Cut marks are small corner marks **outside** every net. They never touch the artwork. No outlines and no tabs. |
| EXP-03b | P1 | Shorter **fold marks** above and below each net where the spine meets the front and back covers (on by default, can be switched off). Outside the artwork, and short enough never to touch the marks of the net above or below. |
| EXP-04 | P1 | There is no separate glue / sticker mode (the layout was identical). Printing on sticker paper only needs a larger **page margin**, so the margin setting carries a hint: for sticker paper such as Avery 53202 use at least 0.25 in (6.35 mm), shown in the chosen unit. Old settings files that still contain a mode load fine; the entry is ignored. |
| EXP-05 | P1 | Nets are never split across pages. More books than fit means more pages. Grid is centered on the page. |
| EXP-06 | P1 | Page margin is adjustable. A margin too small for the marks is rejected. |
| EXP-07 | P2 | **Delivered.** Live preview of the print sheet on the Preview tab, one page at a time with page buttons. It redraws about 0.5 s after the last change. Wraps are cached, so layout-only changes (gap, margin, paper, fold marks) reuse every wrap and a single book's crop redraws only that wrap. A drawing that is out of date stops and is discarded. Changes made on the Books tab never trigger a drawing; opening the Preview tab draws at once if anything changed. |
| EXP-07b | P2 | Clicking a book in the preview opens the same cover dialog as the Books tab (cover choice, crop, zoom). The preview refreshes when it closes. |
| EXP-08 | P1 | One **Save As** step for the PDF: you pick the folder and name the file. The standalone window uses the operating system's own dialog; the browser fallback shows a small folder + file name box. The folder is remembered. |

## SET: Settings

| ID | Phase | Requirement |
|---|---|---|
| SET-01 | P1 | Settings (size, units, DPI, back style, gutter, margin, paper, spine options) are saved to a per-user config file and reloaded on start. |
| SET-02 | P1 | A missing, corrupt, or newer settings file falls back to defaults. It never crashes the app. |
| SET-03 | P1 | Per-book cover choice and crop are remembered between runs. |
| SET-04 | P2 | **Delivered.** Export the output settings to a shareable `.json` file and import one later (for example to switch between book sizes). The file never contains the Google key, the save folder or any per-book data. A file that is not a settings file, or is from a newer version, is refused and changes nothing; unknown or unusable entries are skipped and listed. |

## GUI: Interface

All `P1`. Each is implemented in `controller.py` and tested headlessly; the window itself is not yet launched.

| ID | Requirement |
|---|---|
| GUI-01 | Upload a StoryGraph CSV. A wrong file gives a readable error and changes nothing. The newest year is selected by default. |
| GUI-02 | Filter by year (or all years) and status (or all statuses). Books show in a checklist, grouped: dated (checked), no read date (unchecked). All / None per group. A running count and page estimate. |
| GUI-03 | "Add a book by hand" (title, author, optional ISBN) adds to the checklist. A title is required. |
| GUI-04 | Duplicate editions are flagged in the list. Print order follows the sort setting (author, title, or date). |
| GUI-05 | Settings panel: units, height + width or aspect, thickness, scale calculator, back cover, spine options, paper, glue / sticker, gap, margin, DPI, save folder. Saved automatically. Problems are shown in red and block PDF creation. |
| GUI-06 | Cover dialog per book: every candidate with pixel size, source, quality badge ("Sharp / OK / Low-res") and a "crops a lot" badge. The choice is remembered. |
| GUI-07 | The cover dialog never closes or reloads the book list while you use it; only that book's row updates when you press Done. Upload your own image in the cover dialog. It is copied into the app's config folder and survives restarts. Bad files give a clear error. |
| GUI-08 | Zoom (down to the whole image) and pan sliders with a live preview of the front cover and the whole wrap. Remembered per book, with a reset. |
| GUI-09 | Each row shows its warnings (crop loss, low resolution, no cover, offline). Audiobooks get a hint about square art. |
| GUI-10 | "Fetch covers" and "Fetch edited only" (bottom of box 1 on the Books tab) and "Create PDF" (Preview tab), each with a progress bar. Create PDF opens the Save As step (EXP-08); cancelling builds nothing. |
| GUI-11 | Creating a PDF with invalid settings or nothing selected explains why and writes nothing. |
| GUI-12 | Books without a cover still print (placeholder) and are listed after export as needing a look. |
| DATA-11 | P2 | **Delivered.** Goodreads library exports are accepted as well as StoryGraph, told apart by their columns: ="..." ISBN wrappers undone, "(Series, #1)" removed from titles, Additional Authors added, Exclusive Shelf as status, Date Read (2026/10/30), My Rating (0 = unrated), Binding as format. |
| DATA-12 | P2 | **Delivered.** Date read (2024, 2024-05 or 2024-05-17) and star rating (quarter steps up to 5) can be typed in when adding a book by hand and changed in Edit, for books read without tracking. |
| IMG-05b | P2 | **Delivered.** A cover is judged Sharp / OK / Low-res against at most 300 dpi, however high the print quality is set: printing at 600 dpi no longer turns a 400 dpi cover into "Low-res". Draft (150 dpi) still asks for less. |
| NET-08b | P2 | **Delivered.** A spine/back colour is remembered together with the cover it was picked for and is used only with that cover. If a different edition turns up the next time (or the colour was saved by an older version), the book goes back to Auto with fresh swatches from the new cover. |
| PKG-01 | P3 | **Written, not yet built on all three systems.** `packaging/minibook.spec` (PyInstaller) makes a folder build named MiniBookStudio on Windows, Mac and Linux, with the bundled font, icons and the NiceGUI and window-backend files. Placeholder icons are in `assets/` (png, ico, icns). |
| PKG-02 | P3 | **Delivered.** The launcher works once packaged: `freeze_support`, and a no-console build gets harmless output streams. The window is the default; the browser is the fallback if the window cannot open. |
| PKG-03 | P3 | **Delivered.** `--selftest` checks a build has its fonts and libraries and can make a PDF, an SVG, the test print and a workspace round trip, without opening a window (`--log FILE` for windowed Windows builds); `--version` prints the version. |
| PKG-04 | P3 | **Written, not yet run.** `.github/workflows/build.yml` runs the tests, then builds on Windows, Mac (Apple Silicon) and Linux, self-tests each build and uploads it; one failing system does not hide the others. |
| PKG-05 | P3 | **Written, not yet run.** Pushing a tag such as `v0.1.0` makes a GitHub release with the three downloads and a checksum file. Other runs never publish. |
| PKG-06 | P3 | **Delivered.** Each download holds the app, `samples/`, the licence and a READ ME FIRST note that explains the unsigned-app warning for that system. Windows is a zip, Mac a zip of the app, Linux a tar.gz holding an AppImage. |
| ABOUT-01 | P3 | **Delivered.** An info button in the header opens an About window with the version, tagline, the not-affiliated notice, a plain-language note on what the app contacts and what stays on the computer, credits (Open Library, Google Books, DejaVu font, libraries), the licence and the project link. The version lives in one place (`minibook/about.py`). |
| SAMPLE-01 | P3 | **Delivered.** `samples/sample_library.csv` ships with the app: 13 public-domain classics in StoryGraph's format, with partial star ratings, an audiobook, a long title, one read book with no date and one to-read book, so a new user can try every feature without an export file. Instead of an in-app sample button. |
| EXP-10 | P2 | **Delivered.** "Create SVG" on the Preview tab writes the same sheets as SVG: real millimetre page size, each wrap's picture embedded as a JPEG of at most 300 dpi (a 600 dpi PNG sheet reached 21 MB and would not open), cut and fold marks as vector lines, one group per book. One page keeps the file name; several pages get _page1, _page2... |
| TP-01 | P2 | **Delivered.** "Test print" writes a one-page PDF: a ruler across the top (inches with 1/8 inch ticks, or millimetres when that is the unit), an outlined first row of three books with the spine edges drawn, and spines reading "Min text size" (the smallest allowed), "Max text size" (the largest the spine allows) and "Title Wrapped to two lines" (two lines forced even when wrapping is off). |
| TP-02 | P2 | **Delivered.** The first ticked book is printed as a full wrap under the first row, with cut and fold marks. With none ticked the page says so. The settings (paper, board size, dpi) and "print at 100%" are written on the page. There is no calibration square; the ruler does that job. |
| WS-01 | P2 | **Delivered.** "Save workspace" writes one `.minibook` file holding every book (from the CSV and added by hand, with edits, dates and ratings), the year and status filter, which books are ticked, and the book order settings. "Open workspace" on the Books tab restores all of it and replaces what was there. |
| WS-02 | P2 | **Delivered.** The cover in use for each book, its crop, zoom and spine colour are saved, with the cover pictures inside the file, so opening a workspace needs no internet and the PDF comes out the same. |
| WS-03 | P2 | **Delivered.** Images the user uploaded are saved in the file, including ones not currently in use, and stay offered as "User added" cards after opening. |
| WS-04 | P2 | **Delivered.** The Google key and the save folder are never written to a workspace and are kept when one is opened. |
| WS-05 | P2 | **Delivered.** The output settings (sizes, margins, back style and so on) travel with the workspace. |
| WS-08 | P2 | **Delivered.** A file that is not a workspace, is damaged, too large or from a newer version is refused with a plain message and nothing changes. |
| NET-08 | P2 | **Delivered.** Per-book spine and back colour, chosen in the cover window: a 3x3 grid of Auto (the automatic pick), Black, White and the six most common colours of the cover. Remembered per book; the preview redraws only that book. |
| IMG-17 | P2 | **Delivered.** An uploaded image appears as a "User added" card in the cover list with its size and the same Sharp / crops-a-lot badges. It stays on file and in the list when another cover is chosen, and can be chosen again. |
| GUI-17 | P2 | Cover window layout: tighter cards, the upload sits in the bottom row level with Done, the crop side has no scroll bar, the zoom slider is not clipped. |
| GUI-16 | Preview tab layout: the settings and the sheet are two independent panes; the page itself does not scroll. A zoom bar along the bottom of the window (Preview tab only) scales the sheet from 25% to 300% without redrawing it; beyond 125% the sheet is drawn at twice the resolution so it stays sharp. |
| GUI-15 | **Two tabs.** *Books*: CSV, filters, add by hand, Google key, the Fetch buttons, the checklist. *Preview*: all output settings (size, back cover, spine, print sheet, quality), settings export/import, live preview, Create PDF. |
| GUI-13 | Opens in a native window when pywebview is installed, otherwise in the browser (`--browser` forces it). |
| GUI-14 | Smooth scrolling: list thumbnails are small images served by URL and cached by the browser, so scrolling and redrawing never re-send covers. Editing a book redraws only its row unless the sort order changes. |

## TST: Verification

| ID | Phase | Requirement |
|---|---|---|
| TST-01 | P1 | Each P1 requirement above has at least one test that names its ID. |
| TST-02 | P1 | The real StoryGraph export is parsed in a test, with edge cases from that file. |
| TST-03 | P1 | PDF tests measure the output file: image sizes, mark positions, page count. |
| TST-04 | P1 | Network code is tested with stand-in responses. A live check command is provided for the user's machine. |
