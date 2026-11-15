# MiniBook Studio

Turns your reading list (a StoryGraph or Goodreads CSV, or titles you type in) into print-ready wraps for
mini books: back, spine and front on one sheet with cut and fold marks, covers found automatically, and a
live preview. Output is PDF or SVG, for any mini book made from same-size boards. See `REQUIREMENTS.md` for the
full plan, phase tags and a table of what has and has not been verified.

MiniBook Studio is an independent project. It is not made by, or affiliated with, StoryGraph, Goodreads or
Amazon. Covers come from Open Library, Google Books and Amazon's public image addresses and are downloaded
to your own computer, never redistributed. Licensed under the MIT licence (`LICENSE`); the bundled DejaVu
Sans Condensed font keeps its own licence (`assets/fonts/LICENSE-DejaVu.txt`).

**Try it first:** `samples/sample_library.csv` is a small made-up reading list of public-domain classics. Drop it
onto the Books tab to see covers, spines, the preview and the test print without needing an export of your own.

## Download

Ready-made downloads are on the project's Releases page once the first version is published. Every one opens
MiniBook Studio as its own desktop window, never in a web browser, and none needs a terminal.

| System | Download | How |
| --- | --- | --- |
| Windows | `MiniBook-Studio-Setup-<version>.exe` | Double-click, then Next. A portable `.zip` is also there if you prefer no install. |
| Mac (Apple Silicon) | `MiniBook-Studio-<version>-macos-arm64.dmg` | Open it and drag the app to Applications. |
| Linux (Debian, Ubuntu, Mint) | `minibook-studio_<version>_amd64.deb` | Double-click to install; any needed libraries come with it. |
| Linux (other) | `MiniBook-Studio-<version>-x86_64.AppImage` | Right-click, Properties, allow running as a program, then double-click. |

The apps are not signed yet, so Windows and macOS ask you to confirm the first time you open one (see the
**READ ME FIRST** note). Windows needs Microsoft's WebView2, which is built into Windows 11 and current Windows 10;
if it is missing the app says so and links to the free download. Wine is not supported, because it has no WebView2.
If something goes wrong, the app shows a message and keeps a log in its cache folder.

## Run from source (Windows or Linux, Python 3.12)

    python -m venv .venv
    # Windows:  .venv\Scripts\activate        Linux:  source .venv/bin/activate
    pip install -r requirements.txt

On Debian/Ubuntu the virtual environment is **required**: without it pip stops with
"externally-managed-environment". Do not work around that with `--break-system-packages`.

On Linux, pywebview needs a Qt or GTK backend for the standalone window:
`pip install "pywebview[qt]"`. Start the app with:

    python minibook_gui.py            # standalone window
    python minibook_gui.py --browser  # or in your browser (also the fallback if the window cannot open)

## Using the app

The window has two tabs.

**Books tab**
1. Drop in your StoryGraph or Goodreads CSV (or add books by hand, with an optional date read and star rating). Pick the year; read books with no date are
   listed separately and start unchecked.
2. Press **Fetch covers** (right under the filters), then use **Cover** on any book to pick another
   edition, upload your own image, or adjust the crop. Audiobooks often have square art: check those first.
   The Google Books key is under "Cover search key". Nothing is redrawn here, however many covers you change.

**Preview tab**
3. All output settings are on the left. The print sheet on the right updates about half a second after
   you stop changing things. Use the arrows for other pages and the zoom bar at the bottom to zoom. **Click a book** to open its cover dialog.
4. Press **Create PDF** (or **Create SVG**, one file per page). A Save As dialog lets you pick the folder and
   name the file. **Test print** makes a one-page check sheet with a ruler, spine text samples and your first
   book, so you can confirm your printer is printing at 100%.
5. **Export settings** saves the size, back cover, spine and sheet settings to a file; **Import settings**
   loads one (handy for switching between book sizes or sharing). The Google key and your books are never in it.

Other things to know:

- **Fetch edited only** looks up covers just for books you edited.
- **Edit** on any row changes the title, author, ISBN, date read or star rating (CSV edits are remembered on re-import).
- **Save workspace** (Books tab) keeps your books, chosen covers, uploaded images and settings in one `.minibook`
  file; **Open workspace** brings them back. Your Google key is never in it.
- In the Cover dialog, pick the spine and back colour from the cover's own colours, or black or white.
- **Year** has "All years" and **Status** has "All statuses".
- Size units are inches, millimeters or pixels (pixels at your print DPI).
- In the Cover dialog, drag **Zoom** left to show the whole image; empty space gets the spine colour.
- Spine text has a smallest and a largest size, and an option to wrap long titles onto two lines.
- Back cover has three choices: same as the front, a solid colour matching the spine, or that colour with the date read and the star rating (each can be hidden).
- Cut marks surround each wrap; shorter fold marks show where the spine meets each cover.

## How covers are chosen

Every result is graded by comparing its title and author with yours. The picker shows only the good
matches; box sets, omnibuses, study guides, summaries and other titles are left out (and never
downloaded). If a book has no good match, the picker shows the nearest results with a notice, and the
automatic pick says it is unsure. Opening **Cover** also adds other editions of the same book from Open
Library, and Amazon's picture for the ISBN-10 or ASIN is tried too.

## Getting a Google Books API key (optional, free)

Without a key Google often answers "429 Too Many Requests". That is Google's shared quota, not a
fault in the app, and Open Library keeps working. A key gives you your own allowance. The steps
that worked, in Google Cloud Console (console.cloud.google.com):

1. Create a project (any name, for example "Minibooks").
2. **APIs & Services > Library**, search for **Books API**, open it and press **Enable**. Do this
   first: until it is enabled it does not appear in the key's restriction list.
3. **APIs & Services > Credentials > Create credentials > API key**.
4. Under **API restrictions** choose **Restrict key** and tick **Books API** only. Do not pick
   "Google Cloud APIs" or any Cloud Storage entry: they are unrelated.
5. Leave **Application restrictions** on **None**. "Websites" checks the web page making the request,
   which this app does not have. "Android" and "iOS" do not apply. "IP addresses" breaks whenever
   your home IP changes. The API restriction is your protection, so keep the key private.
6. Create the key and paste it into **Books tab > Cover search key** in the app.

The "Service account required" notice in that panel is about the Gemini and Agent Platform APIs and
does not apply to Books.

After saving the key, press **Fetch covers** (or open a book's Cover dialog). Books looked up earlier
are searched again, so Google results appear without restarting the app. Your chosen covers, custom
images and crops are kept. The key is stored as plain text in the app's settings file in your user
config folder: do not share that file or the project folder with it inside. If a key leaks, delete it
in the console and make a new one.

Defaults: board 1.25" tall x 0.75" wide x 0.25" thick. Everything is editable in the Settings panel
and saved automatically.

## Tests

    python -m unittest discover -s tests -t .

565 tests; each names the requirement IDs it covers. Network code is tested with stand-in
responses, and the GUI view against a stand-in for NiceGUI, so the two checks above are the real tests.

## Layout

    minibook_gui.py         launcher for the window
    minibook/gui.py         NiceGUI view (thin)
    minibook/controller.py  all GUI behavior, framework-free and tested
    minibook/csvimport.py   StoryGraph and Goodreads parsing, filtering, sorting
    minibook/covers.py      Open Library + Google Books lookup, disk cache
    minibook/imaging.py     crop, quality check, colors
    minibook/spine.py       spine text fitting and drawing
    minibook/net.py         back + spine + front assembly
    minibook/layout.py      page grid and cut marks
    minibook/pdfexport.py   PDF output
    minibook/svgexport.py   SVG output
    minibook/testprint.py   the one-page test print
    minibook/workspace.py   save and open a whole workspace
    minibook/preview.py     fast cached live preview of the print sheet
    minibook/backface.py    back cover: solid colour, date, star rating
    minibook/settings.py    saved settings and per-book choices
    assets/fonts/           bundled DejaVu Sans Condensed (identical output on every OS)
