"""Load the extension-less scripts as modules."""
import importlib.machinery
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(relpath):
    path = os.path.join(ROOT, relpath)
    name = os.path.basename(relpath).replace("-", "_")
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
