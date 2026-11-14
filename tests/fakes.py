"""Fake-Gemini-Client und Antwort-Builder fuer Tests (keine Netzwerkaufrufe)."""

from google.genai import types


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
