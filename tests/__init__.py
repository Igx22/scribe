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


def seed_final(source, args, text="Reviewed conversation."):
    """Create a structured cache fixture from test-owned data, never an export."""
    import hashlib
    import scribe
    signature = scribe.source_signature(source)
    cache = args.cache_dir / signature["sha256"]
    cache.mkdir(parents=True, exist_ok=True)
    scribe.open_manifest(cache, signature, source)
    turns = []
    for i, turn in enumerate(scribe.report_turns(text)):
        row = {"start": i * 2, "end": i * 2 + 2, "speaker": i + 1,
               "text": turn["text"], "uncertain": False}
        if turn["speaker"] != "UNKNOWN SPEAKER":
            row["speaker_name"] = turn["speaker"]
        turns.append(row)
    final = {"source_name": source.name, "turns": turns, "supplements": [], "duration": len(turns) * 2,
             "provenance": "",
             "api_only": False, "recognizer": "whisperx", "diarizer": "nemotron",
             "status": "complete", "pipeline_complete": True, "source_mode": "gpt-reconciled",
             "sources": {}, "source_reports": []}
    request = {"settings": scribe.recognition_settings(source, args, signature),
               "selection": {"transcription_model": args.transcription_model}}
    if not args.offline:
        model, effort = args.summarize_model or (scribe.DEFAULT_MODEL, scribe.DEFAULT_EFFORT)
        request["selection"]["fusion"] = {"model": model, "effort": effort, "version": 3,
            "prompt": hashlib.sha256((scribe.FUSION_PROMPT + scribe.SINGLE_SOURCE_PROMPT).encode()).hexdigest()}
    reference = scribe.persist_final(cache, request, final)
    log, _ = scribe.output_paths(source, args.output_dir)
    scribe.select_final(cache, reference, log, request)
    transcript = scribe.materialize_final(cache, reference, final, source)
    scribe.atomic_write(log, transcript)
    scribe.save_json(scribe.output_state_path(cache, log), {**request, "final": reference,
                      "pipeline_complete": True, "transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest()})
    return transcript
