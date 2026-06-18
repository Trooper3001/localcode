"""LLM backends behind one interface (SPEC §3).

All backends expose generate(messages, ...) -> str. OpenRouter speaks chat
completions (streaming SSE); KoboldCPP renders the Qwen3 template and hits
/api/v1/generate. Swapping backends must not change agent behavior.

Stdlib-only (urllib) to keep install friction near zero, mirroring bonsai_dev.
"""
from __future__ import annotations

import json
import threading
import urllib.request
import urllib.error

from . import prompt


class BackendError(RuntimeError):
    pass


class Aborted(Exception):
    """Raised inside generate() when the in-flight request is cancelled."""


class LLMBackend:
    native_tools = False
    fim = False

    def __init__(self):
        self._abort = threading.Event()
        self._resp = None      # current open HTTP response (for hard abort)
        self._lock = threading.Lock()
        self.last_finish_reason = None   # "stop" | "length" (truncated) | ...

    def generate(self, messages, *, stop=None, max_tokens=1024,
                 temperature=0.3, think=True, on_token=None) -> str:
        raise NotImplementedError

    def health(self) -> bool:
        raise NotImplementedError

    def abort(self):
        """Cancel the current generation — closes the socket so the read raises."""
        self._abort.set()
        with self._lock:
            if self._resp is not None:
                try:
                    self._resp.close()
                except Exception:
                    pass

    def _begin(self, resp):
        with self._lock:
            self._resp = resp

    def _end(self):
        with self._lock:
            self._resp = None


def _post(url, payload, headers, timeout=600):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    return urllib.request.urlopen(req, timeout=timeout)


class OpenRouterBackend(LLMBackend):
    def __init__(self, base_url, api_key, model):
        super().__init__()
        if not api_key:
            raise BackendError(
                "no OpenRouter API key. Set OPENROUTER_API_KEY (or keep test.py for now)."
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localcode.dev",
            "X-Title": "localcode",
        }

    def generate(self, messages, *, stop=None, max_tokens=1024,
                 temperature=0.3, think=True, on_token=None) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "reasoning": {"enabled": bool(think)},
        }
        if stop:
            payload["stop"] = stop
        self._abort.clear()
        try:
            resp = _post(self.base_url + "/chat/completions", payload, self._headers())
        except urllib.error.HTTPError as e:
            raise BackendError(f"OpenRouter HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}")
        except urllib.error.URLError as e:
            raise BackendError(f"OpenRouter unreachable: {e}")

        self._begin(resp)
        self.last_finish_reason = None
        chunks = []
        try:
            for raw in resp:
                if self._abort.is_set():
                    raise Aborted()
                line = raw.decode(errors="ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choice = obj.get("choices", [{}])[0]
                if choice.get("finish_reason"):
                    self.last_finish_reason = choice["finish_reason"]
                tok = choice.get("delta", {}).get("content")
                if tok:
                    chunks.append(tok)
                    if on_token:
                        on_token(tok)
        except Aborted:
            raise
        except Exception:
            # socket closed by abort() from another thread → treat as abort
            if self._abort.is_set():
                raise Aborted()
            raise
        finally:
            self._end()
        return prompt.strip_think("".join(chunks))

    def health(self) -> bool:
        try:
            req = urllib.request.Request(self.base_url + "/models", headers=self._headers())
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception:
            return False


class KoboldCppBackend(LLMBackend):
    def __init__(self, base_url, model=""):
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(self, messages, *, stop=None, max_tokens=1024,
                 temperature=0.3, think=True, on_token=None) -> str:
        rendered = prompt.render_qwen3(messages, think=think)
        self._genkey = f"lc{threading.get_ident()}"
        payload = {
            "prompt": rendered,
            "max_length": max_tokens,
            "temperature": temperature,
            "rep_pen": 1.07,
            "stop_sequence": (stop or []) + ["<|im_end|>"],
            "trim_stop": True,
            "genkey": self._genkey,
        }
        self._abort.clear()
        try:
            resp = _post(self.base_url + "/api/v1/generate", payload,
                         {"Content-Type": "application/json"})
            self._begin(resp)
            obj = json.loads(resp.read().decode(errors="ignore"))
        except urllib.error.URLError as e:
            raise BackendError(f"KoboldCPP unreachable at {self.base_url}: {e}")
        except Exception:
            if self._abort.is_set():
                raise Aborted()
            raise
        finally:
            self._end()
        text = obj.get("results", [{}])[0].get("text", "")
        if on_token:
            on_token(text)
        return prompt.strip_think(text)

    def abort(self):
        # KoboldCPP: tell the server to stop generating, then close the socket.
        try:
            _post(self.base_url + "/api/extra/abort",
                  {"genkey": getattr(self, "_genkey", "")},
                  {"Content-Type": "application/json"}, timeout=5)
        except Exception:
            pass
        super().abort()

    def health(self) -> bool:
        try:
            urllib.request.urlopen(self.base_url + "/api/v1/model", timeout=5)
            return True
        except Exception:
            return False


def make_backend(cfg) -> LLMBackend:
    if cfg.backend == "openrouter":
        return OpenRouterBackend(cfg.base_url, cfg.api_key, cfg.model)
    if cfg.backend == "koboldcpp":
        return KoboldCppBackend(cfg.base_url, cfg.model)
    raise BackendError(f"unknown backend {cfg.backend}")
