"""Development-only plugin hot reload tests (#411).

Reloading re-imports a plugin module in-process, so it must be impossible in
production and must never replace a working module with a broken one.
"""

from __future__ import annotations

import sys

import pytest

from app.services.plugins import (
    Plugin,
    PluginLoadError,
    PluginManifest,
    PluginRegistry,
    PluginReloadError,
    hot_reload_enabled,
)

MODULE = "hot_reload_pkg.mod"


def _manifest(entry_point=f"{MODULE}:HotPlugin"):
    return PluginManifest.from_dict(
        {
            "id": "hot-reload-plugin",
            "name": "Hot Reload",
            "version": "1.0.0",
            "description": "test",
            "author": "tester",
            "entry_point": entry_point,
            "capabilities": ["PROJECT_READ"],
        }
    )


def _write_module(path, version: str) -> None:
    path.write_text(
        f"VERSION = {version!r}\n"
        "class HotPlugin:\n"
        "    def __init__(self, app=None, manifest=None):\n"
        "        self.app = app\n"
        "        self.manifest = manifest\n"
        "    def version(self):\n"
        "        return VERSION\n",
        encoding="utf-8",
    )


@pytest.fixture()
def reloadable_module(tmp_path, monkeypatch):
    package = tmp_path / "hot_reload_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    module_path = package / "mod.py"
    _write_module(module_path, "one")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        yield module_path
    finally:
        sys.modules.pop(MODULE, None)
        sys.modules.pop("hot_reload_pkg", None)


def _development_app(app):
    app.config["ENVIRONMENT"] = "development"
    app.config["PLUGIN_HOT_RELOAD"] = True
    app.debug = True
    return app


class TestHotReloadGuard:
    def test_enabled_only_for_debug_development(self, app):
        _development_app(app)
        assert hot_reload_enabled(app) is True

        app.debug = False
        assert hot_reload_enabled(app) is False

        app.debug = True
        app.config["ENVIRONMENT"] = "production"
        assert hot_reload_enabled(app) is False

        app.config["ENVIRONMENT"] = "development"
        app.config["PLUGIN_HOT_RELOAD"] = False
        assert hot_reload_enabled(app) is False

    def test_reload_is_refused_in_production(self, app, reloadable_module):
        app.config["ENVIRONMENT"] = "production"
        app.config["PLUGIN_HOT_RELOAD"] = True
        app.debug = True
        registry = PluginRegistry()
        plugin = Plugin(_manifest())
        registry.register(plugin)
        registry.load_plugin("hot-reload-plugin")
        previous = plugin.module

        with pytest.raises(PluginReloadError):
            registry.reload_plugin("hot-reload-plugin", app=app)

        assert plugin.module is previous


class TestHotReload:
    def test_reimports_a_changed_module(self, app, reloadable_module):
        _development_app(app)
        registry = PluginRegistry()
        plugin = Plugin(_manifest())
        registry.register(plugin)
        registry.load_plugin("hot-reload-plugin")
        assert plugin.get_instance().version() == "one"

        _write_module(reloadable_module, "two")
        registry.reload_plugin("hot-reload-plugin", app=app)

        assert plugin.get_instance().version() == "two"
        assert plugin.module is sys.modules[MODULE]

    def test_failed_reload_keeps_the_working_module(self, app, reloadable_module):
        _development_app(app)
        registry = PluginRegistry()
        plugin = Plugin(_manifest())
        registry.register(plugin)
        registry.load_plugin("hot-reload-plugin")
        previous = plugin.module

        reloadable_module.write_text("raise RuntimeError('broken edit')\n", encoding="utf-8")
        with pytest.raises(PluginLoadError):
            registry.reload_plugin("hot-reload-plugin", app=app)

        assert plugin.module is previous
        assert sys.modules[MODULE] is previous
