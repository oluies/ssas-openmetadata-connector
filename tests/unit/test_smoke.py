"""Smoke test: the package imports (parser/enum/redact modules are SDK-free)."""
import importlib


def test_package_imports():
    mod = importlib.import_module("ssas_om")
    assert mod.__version__


def test_sdk_free_modules_import():
    # these must not require the heavy OpenMetadata SDK
    for name in ("redact", "enums", "csdl", "mdschema", "classify", "client"):
        importlib.import_module(f"ssas_om.{name}")
