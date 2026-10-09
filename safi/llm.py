import httpx

from safi import config


class LLMClient:
    """One configured LLM endpoint (OpenAI-compatible chat completions).

    If SAFI_LLM_ENDPOINT is not configured the service falls back to a
    deterministic extractive answerer that only quotes role-permitted context.
    """

    def __init__(self, endpoint=None, api_key=None, model=None, timeout=None):
        self.endpoint = (endpoint if endpoint is not None else config.LLM_ENDPOINT).strip()
        self.api_key = api_key if api_key is not None else config.LLM_API_KEY
        self.model = model if model is not None else config.LLM_MODEL
        self.timeout = timeout if timeout is not None else config.LLM_TIMEOUT

    @property
    def configured(self):
        return bool(self.endpoint)

    @property
    def _url(self):
        if self.endpoint.endswith("/chat/completions"):
            return self.endpoint
        return self.endpoint.rstrip("/") + "/chat/completions"

    def complete(self, system_prompt, user_prompt):
        if not self.configured:
            raise RuntimeError("LLM endpoint not configured")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self._url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        return data["choices"][0]["message"]["content"]
