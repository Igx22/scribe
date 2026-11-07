"""Load this portable application's sources without installing the project."""
from contextlib import contextmanager
from pathlib import Path
import sys
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@contextmanager
def runtime_paths(*, cache_dir=None, models_dir=None):
    """Isolate main() tests without exposing filesystem overrides in the CLI."""
    import scribe
    build_parser = scribe.build_parser

    def isolated_parser():
        parser = build_parser()
        if cache_dir is not None:
            parser.set_defaults(cache_dir=cache_dir)
        if models_dir is not None:
            parser.set_defaults(models_dir=models_dir)
        return parser

    with patch.object(scribe, "build_parser", side_effect=isolated_parser):
        yield
