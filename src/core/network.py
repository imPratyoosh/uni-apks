import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests
from curl_cffi.requests import exceptions as req_exc

from src.core.logger import epr


class NetworkError(Exception):
    pass

class ResourceNotFoundError(NetworkError):
    """Raised when a remote resource returns HTTP 404."""

def _get_lock(locks: dict, mu: threading.Lock, key) -> threading.Lock:
    with mu:
        return locks.setdefault(key, threading.Lock())

class NetworkManager:
    def __init__(self) -> None:
        self.session = requests.Session(impersonate="firefox147")
        token = os.getenv("GITHUB_TOKEN")
        self._gh_headers: dict[str, str] = {"Authorization": f"token {token}"} if token else {}
        self._domain_locks: dict[str, threading.Lock] = {}
        self._domain_mu = threading.Lock()
        self._dest_locks: dict[Path, threading.Lock] = {}
        self._dest_mu = threading.Lock()

    def get(self, url: str, headers: dict[str, str] | None = None) -> str:
        try:
            with _get_lock(self._domain_locks, self._domain_mu, urlparse(url).netloc):
                time.sleep(0.5)
                resp = self.session.get(url, timeout=(5, 10), allow_redirects=True, headers=headers, verify=True)

            if resp.status_code == 404:
                raise ResourceNotFoundError(f"Not found (404): {url}")

            if resp.status_code >= 400:
                epr(f"HTTP {resp.status_code} for {url}")
                resp.raise_for_status()

            return resp.text
        except req_exc.RequestException:
            raise NetworkError(f"Request failed: {url}") from None

    def gh_get(self, url: str) -> str:
        return self.get(url, headers=self._gh_headers)

    def download(self, url: str, dest: Path, headers: dict[str, str] | None = None) -> None:
        if dest.exists():
            return

        with _get_lock(self._dest_locks, self._dest_mu, dest):
            if dest.exists():
                return

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f"tmp.{dest.name}")
            tmp.unlink(missing_ok=True)
            try:
                with _get_lock(self._domain_locks, self._domain_mu, urlparse(url).netloc):
                    time.sleep(0.5)
                    resp = self.session.get(url, timeout=(5, 300), stream=True, allow_redirects=True, headers=headers, verify=True)
                    resp.raise_for_status()

                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1048576):
                        fh.write(chunk)
                tmp.replace(dest)
            except req_exc.RequestException:
                raise NetworkError(f"Download failed: {url}") from None
            finally:
                tmp.unlink(missing_ok=True)

    def gh_download(self, url: str, dest: Path) -> None:
        self.download(url, dest, headers=self._gh_headers | {"Accept": "application/octet-stream"})

    def __enter__(self) -> "NetworkManager":
        return self

    def __exit__(self, *_: object) -> None:
        self.session.close()