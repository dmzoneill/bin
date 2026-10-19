"""Shared clients and helpers for the scripts in this directory.

Scripts are executed directly, so Python puts this directory on ``sys.path``
and ``import binlib`` resolves without an extra install step.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib
import json
import os
import sys
from collections.abc import Callable
from typing import Any, NoReturn


class OpenAIError(Exception):
    """Raised when a chat or embedding HTTP call fails."""


# Failures from reading a local text file. UnicodeDecodeError is a UnicodeError.
FILE_READ_ERRORS = (OSError, UnicodeError)
# Failures from a response body that is not the shape the caller expects.
RESPONSE_PARSE_ERRORS = (ValueError, KeyError, IndexError, TypeError, AttributeError)


class OpenAIProvider:
    """Chat-completions client. Callers pick a factory that sets the options."""

    def __init__(self, api_key: str | None, settings: dict[str, Any]) -> None:
        """Store credentials and the call style selected by a factory."""
        self.api_key = api_key
        self.model = settings["model"]
        self.temperature = settings["temperature"]
        self.timeout = settings["timeout"]
        self.on_error = settings["on_error"]
        self.endpoint = "https://api.openai.com/v1/chat/completions"
        self.embedding_endpoint = "https://api.openai.com/v1/embeddings"

    def ask(self, model: str, system: str, user: str) -> str:
        """Send a chat completion using the model passed by the caller."""
        return self._post_chat(model, system, user)

    def improve_text(self, prompt: str, text: str) -> str:
        """Send a chat completion using the model stored on this client."""
        return self._post_chat(self.model, prompt, text)

    def generate_commit_message(self, prompt: str, text: str) -> str:
        """Return a commit message. Same request as ``improve_text``."""
        return self.improve_text(prompt, text)

    def get_embeddings(self, text: str) -> list[Any]:
        """Return an embedding from ``text-embedding-ada-002``."""
        requests = _requests()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "text-embedding-ada-002",
            "input": text,
        }
        response = requests.post(
            self.embedding_endpoint,
            json=body,
            headers=headers,
            timeout=120,
        )
        if response.status_code == 200:
            return response.json()["data"][0]["embedding"]
        raise OpenAIError(
            f"Embedding API call failed: {response.status_code} - {response.text}"
        )

    def _post_chat(self, model: str | None, system: str, user: str) -> str:
        requests = _requests()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        try:
            response = requests.post(
                self.endpoint, json=body, headers=headers, timeout=self.timeout
            )
        except requests.exceptions.RequestException as exc:
            return self._handle_request_error(exc)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        message = f"OpenAI API call failed: {response.status_code} - {response.text}"
        if self.on_error == "exit":
            print(message)
            sys.exit(1)
        raise OpenAIError(message)

    def _handle_request_error(self, exc: Exception) -> NoReturn:
        if self.on_error == "exit":
            print(f"Request failed: {str(exc)}")
            sys.exit(1)
        if self.on_error == "raise-request":
            raise OpenAIError(f"Request failed: {str(exc)}") from exc
        raise exc


def pinecone_openai() -> OpenAIProvider:
    """Client used by the Pinecone query scripts (temperature 0.8, timeout 120)."""
    return _provider(True, None, 0.8, 120, "raise")


def summarize_openai(timeout: int) -> OpenAIProvider:
    """Client for commit and docstring summaries (temperature 0.3)."""
    model = _model_from_env("OPENAI_MODEL", "gpt-4o-mini")
    return _provider(True, model, 0.3, timeout, "raise")


def journal_openai() -> OpenAIProvider:
    """Client used by the journal report (temperature 0.4, wraps request errors)."""
    model = _model_from_env("AI_MODEL", "gpt-4")
    return _provider(False, model, 0.4, 120, "raise-request")


def wordpress_openai() -> OpenAIProvider:
    """Client used by the WordPress scripts (exits on HTTP failure)."""
    model = _model_from_env("AI_MODEL", None)
    return _provider(False, model, 0.4, 120, "exit")


def pinecone_argument_parser() -> argparse.ArgumentParser:
    """Build the parser shared by the Pinecone query scripts."""
    parser = argparse.ArgumentParser(
        description="Query the Pinecone index and interact with OpenAI."
    )
    parser.add_argument(
        "pinecone_query",
        type=str,
        help="The query text to search for in the Pinecone index.",
    )
    return parser


def require_pinecone_client(pinecone_cls: Any = None) -> Any:
    """Return a Pinecone client or exit when ``PINECONE_API_KEY`` is missing."""
    api_key = os.getenv("PINECONE_API_KEY")
    if not api_key:
        print("Pinecone API key is missing. Please set PINECONE_API_KEY.")
        sys.exit(1)
    if pinecone_cls is None:
        pinecone_cls = _pinecone().Pinecone
    return pinecone_cls(api_key=api_key, environment="us-east-1")


def query_pinecone_index(client: Any, query_text: str, top_k: int) -> tuple[Any, Any]:
    """Embed ``query_text`` and query the index named after the working directory."""
    index_name = os.path.basename(os.getcwd()).replace("_", "-")
    index = client.Index(name=index_name)
    provider = pinecone_openai()
    query_vector = provider.get_embeddings(query_text)
    results = index.query(vector=query_vector, top_k=top_k, include_metadata=True)
    return provider, results


def format_pinecone_matches(results: dict[str, Any]) -> str:
    """Build the match listing printed by the Pinecone query scripts."""
    matches_with_info = ""
    for index, result in enumerate(results["matches"]):
        file_info, match_text = _match_text(result)
        matches_with_info += (
            f"Match {index + 1}: File: {file_info}\nText: {match_text}\n\n"
        )
    return matches_with_info


def get_file_digest(file_path: str) -> str:
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        while chunk := handle.read(8192):
            digest.update(chunk)
    return digest.hexdigest()


def load_json_cache(cache_file: str) -> Any:
    """Load a JSON cache file, or return an empty dict when it is missing."""
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def save_json_cache(cache_file: str, cache: Any) -> None:
    """Write a cache mapping back to JSON."""
    with open(cache_file, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, indent=4)


def index_changed_python_files(
    codebase_dir: str,
    cache: Any,
    upload: Callable[[str, str], None],
    upload_errors: tuple[type[BaseException], ...] = (),
) -> None:
    """Upload ``.py`` files whose digest is not already stored in ``cache``.

    ``ValueError`` is reported as a skip. Classes in ``upload_errors`` are logged
    and the walk continues, which is how the index scripts treated client failures.
    """
    for root, _dirs, filenames in os.walk(codebase_dir):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            file_path = os.path.join(root, filename)
            file_digest = get_file_digest(file_path)
            if file_path in cache and cache[file_path] == file_digest:
                print(f"Skipping {file_path}: No changes detected.")
                continue
            with open(file_path, "r", encoding="utf-8") as handle:
                code = handle.read()
            try:
                upload(file_path, code)
            except ValueError as exc:
                print(f"Skipping {file_path}: {exc}")
                continue
            except upload_errors as exc:
                print(f"Error processing {file_path}: {exc}")
                continue
            cache[file_path] = file_digest
            print(f"Processed and uploaded {file_path}")


def require_nonempty_text(text: str) -> None:
    """Reject blank embedding input the same way both indexers do."""
    if not text.strip():
        raise ValueError("Input text cannot be empty.")


def search_image_url_unsplash(query: str, api_key: str | None) -> str | None:
    """Return an Unsplash image URL for ``query``.

    This is the definition that actually runs in the WordPress scripts: the
    earlier copy in each file was overridden and did not handle errors.
    """
    requests = _requests()
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {api_key}"}
    params = {"query": query, "per_page": 1, "orientation": "landscape"}
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        if data["results"]:
            return data["results"][0]["urls"]["regular"]
    return None


def search_youtube_video(topic: str, api_key: str | None) -> str | None:
    """Return an embed URL for the first video matching ``topic``."""
    requests = _requests()
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "q": topic,
        "type": "video",
        "maxResults": 1,
        "videoEmbeddable": "true",
        "key": api_key,
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if data["items"]:
            return f"https://www.youtube.com/embed/{data['items'][0]['id']['videoId']}"
    return None


def upload_image_to_wordpress(
    image_url: str,
    image_name: str,
    media_url: str,
    username: str | None,
    application: str | None,
) -> str | None:
    """Download ``image_url`` and upload it to a WordPress media endpoint."""
    requests = _requests()
    try:
        img_data = requests.get(image_url).content
        token = base64.b64encode(f"{username}:{application}".encode()).decode()
        headers = {
            "Content-Disposition": f"attachment; filename={image_name}",
            "Content-Type": "image/jpeg",
            "Authorization": f"Basic {token}",
        }
        response = requests.post(media_url, headers=headers, data=img_data)
        if response.status_code == 201:
            return response.json().get("source_url")
        print(f"WordPress upload failed: {response.status_code} - {response.text}")
    except (requests.exceptions.RequestException,) + RESPONSE_PARSE_ERRORS as exc:
        print(f"Image upload failed: {exc}")
    return None


def append_enrichment_to_post(content: str, video_url: str | None) -> str:
    """Append the further-learning embed when a video URL is available."""
    enrichment = ""
    if video_url:
        enrichment = "\n\n<hr><h2>📚 Further Learning</h2>\n"
        enrichment += (
            "<p>🎥 Watch this video for more:</p>\n"
            f'<iframe width="710" height="415" src="{video_url}" '
            'frameborder="0" allowfullscreen></iframe>\n'
        )
    return content + enrichment


def _provider(
    require_key: bool,
    model: str | None,
    temperature: float,
    timeout: int,
    on_error: str,
) -> OpenAIProvider:
    api_key = os.getenv("AI_API_KEY")
    if require_key and not api_key:
        raise EnvironmentError("AI_API_KEY not set in environment.")
    return OpenAIProvider(
        api_key,
        {
            "model": model,
            "temperature": temperature,
            "timeout": timeout,
            "on_error": on_error,
        },
    )


def _model_from_env(env_name: str, default: str | None) -> str | None:
    if default is None:
        return os.getenv(env_name)
    return os.getenv(env_name, default)


def _match_text(result: dict[str, Any]) -> tuple[Any, Any]:
    match_text = result["metadata"].get("text", None)
    file_info = result["metadata"].get("file", "No file info")
    if match_text is None:
        file_path = result["metadata"].get("file", "")
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as handle:
                    match_text = handle.read()
            except FILE_READ_ERRORS as exc:
                print(f"Error reading file {file_path}: {exc}")
                match_text = "No text available in file."
        else:
            match_text = "No file or text available."
    return file_info, match_text


def openai_client_errors(openai_module: Any) -> tuple[type[BaseException], ...]:
    """OS and OpenAI failures raised while embedding one source file."""
    legacy = getattr(openai_module, "error", None)
    return exception_types(
        OSError,
        KeyError,
        IndexError,
        TypeError,
        RuntimeError,
        getattr(openai_module, "OpenAIError", None),
        getattr(openai_module, "APIError", None),
        getattr(legacy, "OpenAIError", None),
        getattr(legacy, "APIError", None),
    )


def exception_types(*candidates: Any) -> tuple[type[BaseException], ...]:
    """Return the exception classes in ``candidates``.

    ``Exception`` and ``BaseException`` are dropped so callers stay specific.
    """
    found: list[type[BaseException]] = []
    for item in candidates:
        if item in (Exception, BaseException):
            continue
        if (
            isinstance(item, type)
            and issubclass(item, BaseException)
            and item not in found
        ):
            found.append(item)
    return tuple(found)


def _requests() -> Any:
    """Load requests the first time an HTTP helper runs."""
    return importlib.import_module("requests")


def _pinecone() -> Any:
    """Load pinecone the first time a query script builds a client."""
    return importlib.import_module("pinecone")
