"""A stand-in for `nicegui`, only for exercising OUR view code without the real package.

It records every element created and lets tests invoke the handlers we registered. It cannot
tell whether we are using NiceGUI's real API correctly: that needs the real package.
"""
import sys
import types


class El:
    registry: list = []
    stack: list = []

    def __init__(self, kind, args, kwargs):
        self.kind, self.args, self.kwargs = kind, args, kwargs
        self.value = kwargs.get("value")
        self.calls = []
        El.registry.append(self)

    def calls_style(self):
        return " ".join(a[0] for n, a, _k in self.calls if n == "style" and a)

    @property
    def text(self):
        return str(self.args[0]) if self.args else str(self.kwargs.get("label", ""))

    def __enter__(self):
        El.stack.append(self)
        return self

    def __exit__(self, *exc):
        El.stack.pop()
        return False

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def method(*a, **k):
            self.calls.append((name, a, k))
            if name == "set_value" and a:
                self.value = a[0]
            if name == "set_text" and a:
                self.args = (a[0],) + tuple(self.args[1:])
            return self
        return method


class Refreshable:
    def __init__(self, fn):
        self.fn, self.last = fn, ((), {})

    def __call__(self, *a, **k):
        self.last = (a, k)
        return self.fn(*a, **k)

    def refresh(self, *a, **k):
        args, kwargs = self.last
        return self.fn(*args, **kwargs)


class Ui:
    def __init__(self):
        self.notifications = []
        self.page_fn = None
        self.run_kwargs = None
        self.downloads = []

    def refreshable(self, fn):
        return Refreshable(fn)

    def notify(self, message, **kw):
        self.notifications.append((message, kw))

    def page(self, path):
        def deco(fn):
            self.page_fn = fn
            return fn
        return deco

    def run(self, **kw):
        self.run_kwargs = kw

    def colors(self, **kw):
        pass

    def download(self, *a, **k):
        self.downloads.append((a, k))

    def __getattr__(self, kind):
        if kind.startswith("__"):
            raise AttributeError(kind)
        return lambda *a, **k: El(kind, a, k)


class App:
    def __init__(self):
        self.routes = {}

    def get(self, path):
        def deco(fn):
            self.routes[path] = fn
            return fn
        return deco


class Run:
    @staticmethod
    async def io_bound(fn, *a, **k):
        return fn(*a, **k)


def install():
    mod = types.ModuleType("nicegui")
    mod.ui = Ui()
    mod.run = Run()
    mod.app = App()
    sys.modules["nicegui"] = mod
    El.registry.clear()
    El.stack.clear()
    # forget any earlier import of the view, including the attribute the package keeps on itself
    sys.modules.pop("minibook.gui", None)
    pkg = sys.modules.get("minibook")
    if pkg is not None and hasattr(pkg, "gui"):
        delattr(pkg, "gui")
    return mod


def find(kind=None, text=None, where=None):
    out = []
    for e in El.registry:
        if kind and e.kind != kind:
            continue
        if text is not None and text not in e.text:
            continue
        if where and not where(e):
            continue
        out.append(e)
    return out
