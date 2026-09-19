"""Smoke-test MCP tool registration for all 3 transcription servers."""
import sys
import types
import os


def _make_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    return m


def _install_stubs() -> None:
    # torch
    torch_stub = _make_stub("torch")
    torch_stub.cuda = types.SimpleNamespace(is_available=lambda: False)
    torch_stub.float16 = "float16"
    torch_stub.float32 = "float32"
    sys.modules["torch"] = torch_stub

    # whisper
    whisper_stub = _make_stub("whisper")
    whisper_stub.available_models = lambda: ["tiny", "base", "small", "medium", "large"]
    whisper_stub.load_model = lambda *a, **kw: None
    sys.modules["whisper"] = whisper_stub

    # pyannote
    pyannote_audio = _make_stub("pyannote.audio")

    class _Pipeline:
        @classmethod
        def from_pretrained(cls, *a, **kw):
            return cls()

    pyannote_audio.Pipeline = _Pipeline
    sys.modules["pyannote"] = _make_stub("pyannote")
    sys.modules["pyannote.audio"] = pyannote_audio
    sys.modules["pyannote.audio.pipelines"] = _make_stub("pyannote.audio.pipelines")

    # pydub — must be a fake package (needs __path__)
    _AudioSegment = type(
        "AudioSegment",
        (),
        {
            "from_file": classmethod(lambda cls, *a, **kw: cls()),
            "empty": classmethod(lambda cls: cls()),
            "export": lambda self, *a, **kw: None,
        },
    )
    pydub_pkg = types.ModuleType("pydub")
    pydub_pkg.__path__ = []  # marks it as a package
    pydub_pkg.AudioSegment = _AudioSegment
    sys.modules["pydub"] = pydub_pkg

    pydub_effects = types.ModuleType("pydub.effects")
    pydub_effects.compress_dynamic_range = lambda seg, **kw: seg
    sys.modules["pydub.effects"] = pydub_effects

    pydub_silence = types.ModuleType("pydub.silence")
    pydub_silence.detect_nonsilent = lambda seg, **kw: []
    sys.modules["pydub.silence"] = pydub_silence

    # openai
    openai_stub = _make_stub("openai")

    class _OpenAI:
        def __init__(self, *a, **kw):
            pass

    openai_stub.OpenAI = _OpenAI
    sys.modules["openai"] = openai_stub

    # misc heavy deps
    for mod in [
        "noisereduce", "scipy", "scipy.io", "scipy.io.wavfile",
        "numpy", "numpy.typing", "runpod", "huggingface_hub",
        "sentence_transformers", "torchaudio",
    ]:
        sys.modules[mod] = _make_stub(mod)


_install_stubs()
sys.path.insert(0, os.getcwd())

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"

SERVERS = [
    ("meta_server",          "src.mcp.servers.meta_server"),
    ("transcripts_server",   "src.mcp.servers.transcripts_server"),
    ("transcription_server", "src.mcp.servers.transcription_server"),
]

all_ok = True
for label, module_path in SERVERS:
    try:
        mod = __import__(module_path, fromlist=["mcp"])
        tools_dict = mod.mcp._tool_manager._tools
        tool_names = sorted(tools_dict.keys())
        print(f"{PASS} {label}: {len(tool_names)} tools registered")
        for t in tool_names:
            print(f"     · {t}")
    except Exception as e:
        import traceback
        print(f"{FAIL} {label}: FAILED — {e}")
        traceback.print_exc()
        all_ok = False
    print()

if all_ok:
    print("ALL SERVERS OK \033[32m✓\033[0m")
else:
    print("SOME SERVERS FAILED \033[31m✗\033[0m")
    sys.exit(1)
