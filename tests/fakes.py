"""Fake-Gemini-Client und Antwort-Builder fuer Tests (keine Netzwerkaufrufe)."""

from google.genai import errors, types


def api_error(code, message="test"):
    """Gemini-Fehler wie vom SDK: ServerError fuer 5xx, sonst ClientError."""
    cls = errors.ServerError if code >= 500 else errors.ClientError
    return cls(code, {"error": {"code": code, "message": message}})


class FakeModels:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def generate_content(self, *, model, contents, config=None):
        snapshot = list(contents) if isinstance(contents, list) else contents
        self.calls.append({"model": model, "contents": snapshot, "config": config})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)

    @property
    def called_models(self):
        """Modell-ID je generate_content-Aufruf, in Aufrufreihenfolge."""
        return [c["model"] for c in self.models.calls]


def text_response(text):
    content = types.Content(role="model", parts=[types.Part(text=text)])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def call_response(*calls):
    """calls: (name, args)-Tupel -> Antwort mit Function-Calls (IDs call-0, call-1, ...)."""
    parts = [
        types.Part(
            function_call=types.FunctionCall(id=f"call-{i}", name=name, args=args)
        )
        for i, (name, args) in enumerate(calls)
    ]
    content = types.Content(role="model", parts=parts)
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def audio_response(data: bytes, mime="audio/wav"):
    """TTS-Antwort: ein Inline-Audio-Part (z. B. WAV oder audio/L16;rate=24000)."""
    part = types.Part(inline_data=types.Blob(data=data, mime_type=mime))
    content = types.Content(role="model", parts=[part])
    return types.GenerateContentResponse(candidates=[types.Candidate(content=content)])


def grounded_response(text, sources):
    """Maps-Grounding-Antwort: Text plus Quellen [(title, uri), ...] in grounding_metadata."""
    content = types.Content(role="model", parts=[types.Part(text=text)])
    metadata = types.GroundingMetadata(
        grounding_chunks=[
            types.GroundingChunk(maps=types.GroundingChunkMaps(title=title, uri=uri))
            for title, uri in sources
        ]
    )
    candidate = types.Candidate(content=content, grounding_metadata=metadata)
    return types.GenerateContentResponse(candidates=[candidate])
