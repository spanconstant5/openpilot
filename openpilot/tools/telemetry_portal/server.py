# ruff: noqa: E501  # Embedded single-file portal HTML is intentionally compact.
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import subprocess
import threading
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from openpilot.tools.telemetry_importer import importer


PORTAL_HOST = "127.0.0.1"
PORTAL_PORT = 8765
REMOTE_ROOTS = (PurePosixPath("/data/media/0/telemetry"), PurePosixPath("/data/media/0/realdata"))
RECORDING_SUFFIXES = (".db", "rlog.zst", "rlog.bz2", "rlog", "fcamera.hevc", "ecamera.hevc", "qcamera.ts", ".eps-telescope.zip")
MAC_RE = re.compile(r"^(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}$", re.IGNORECASE)


class PortalError(RuntimeError):
  pass


@dataclass(frozen=True)
class RemoteFile:
  identifier: str
  path: str
  name: str
  size_bytes: int
  modified_unix: int


def _private_ip(value: str) -> str:
  try:
    address = ipaddress.ip_address(value)
  except ValueError as error:
    raise PortalError("Enter a private IPv4 address or a local MAC address.") from error
  if address.version != 4 or not address.is_private:
    raise PortalError("Only private local-network IPv4 addresses are allowed.")
  return str(address)


def _normalized_mac(value: str) -> str | None:
  value = value.strip().lower()
  if not MAC_RE.fullmatch(value):
    return None
  return value.replace("-", ":")


def resolve_target(value: str, arp_output: str | None = None) -> str:
  """Resolve an IP directly or a MAC address already present in the local ARP cache."""
  value = value.strip()
  mac = _normalized_mac(value)
  if mac is None:
    return _private_ip(value)
  if arp_output is None:
    try:
      arp_output = subprocess.run(["arp", "-a"], check=False, capture_output=True, text=True).stdout
    except OSError as error:
      raise PortalError(f"Could not read the local ARP table: {error}") from error
  for line in arp_output.splitlines():
    fields = line.split()
    if len(fields) >= 2 and _normalized_mac(fields[1]) == mac:
      return _private_ip(fields[0])
  raise PortalError("That MAC address is not in this PC's local ARP table. Connect to the comma network, then enter its IP.")


def _safe_remote_path(value: str) -> PurePosixPath:
  path = PurePosixPath(value)
  if not path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
    raise PortalError("Invalid comma file path.")
  if path.name != "manifest.json" and not path.name.endswith(RECORDING_SUFFIXES):
    raise PortalError("Only known comma recording files can be copied through the portal.")
  if not any(path.is_relative_to(root) for root in REMOTE_ROOTS):
    raise PortalError("That file is outside the comma recording folders.")
  return path


def _file_stat(adb: Path, serial: str, path: PurePosixPath) -> tuple[int, int]:
  output = str(importer.run_adb(adb, serial, ["shell", "stat", "-c", "%Y|%s", str(path)])).strip()
  try:
    modified, size = output.split("|", maxsplit=1)
    return int(modified), int(size)
  except ValueError as error:
    raise PortalError(f"Could not read timestamp for {path.name}.") from error


class PortalState:
  def __init__(self, destination: Path, adb: Path | None = None):
    self.destination = destination.resolve()
    self.adb = importer.find_adb(adb)
    self.serial: str | None = None
    self.files: dict[str, RemoteFile] = {}
    self.lock = threading.Lock()

  def connect(self, target: str) -> dict[str, str]:
    ip = resolve_target(target)
    endpoint = f"{ip}:5555"
    try:
      importer.run_adb(self.adb, None, ["connect", endpoint])
      authorized, unauthorized = importer._device_states(str(importer.run_adb(self.adb, None, ["devices"])))
    except importer.ImportFailure as error:
      raise PortalError(str(error)) from error
    if endpoint in unauthorized:
      raise PortalError("The comma is visible but unauthorized. Accept its ADB authorization prompt and try again.")
    if endpoint not in authorized:
      raise PortalError(f"No authorized comma responded at {endpoint}. Enable ADB and verify the IP/network.")
    self.serial = endpoint
    return {"ip": ip, "serial": endpoint}

  def list_files(self) -> list[RemoteFile]:
    if self.serial is None:
      raise PortalError("Connect to a comma first.")
    paths: list[PurePosixPath] = []
    for root in REMOTE_ROOTS:
      output = str(importer.run_adb(self.adb, self.serial, ["shell", "find", str(root), "-type", "f"]))
      for line in output.splitlines():
        path = PurePosixPath(line.strip())
        if path.name == "manifest.json" or path.name.endswith(RECORDING_SUFFIXES):
          try:
            paths.append(_safe_remote_path(str(path)))
          except PortalError:
            pass
    # Deliberately no date/count limit: every matching recording still present
    # on the comma is available to the owner through this local portal.
    unique_paths = sorted(set(paths), key=str, reverse=True)
    files = []
    for index, path in enumerate(unique_paths, start=1):
      try:
        modified, size = _file_stat(self.adb, self.serial, path)
      except PortalError:
        continue
      files.append(RemoteFile(str(index), str(path), path.name, size, modified))
    self.files = {item.identifier: item for item in files}
    return files

  def copy_file(self, identifier: str) -> Path:
    if self.serial is None:
      raise PortalError("Connect to a comma first.")
    item = self.files.get(identifier)
    if item is None:
      raise PortalError("Refresh the file list and choose a listed file.")
    remote = _safe_remote_path(item.path)
    relative_root = next(root for root in REMOTE_ROOTS if remote.is_relative_to(root))
    destination = self.destination / relative_root.name / remote.relative_to(relative_root)
    importer.pull(self.adb, self.serial, remote, destination)
    return destination


PAGE = """<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>Comma File Portal</title>
<style>body{font:16px system-ui,sans-serif;max-width:980px;margin:2rem auto;padding:0 1rem;background:#101418;color:#edf2f5}input,button{font:inherit;padding:.55rem;margin:.2rem}button{cursor:pointer;background:#65bf45;border:0;border-radius:5px;color:#071006}#status{min-height:1.5rem;color:#b8c5cb}table{width:100%;border-collapse:collapse;margin-top:1rem}td,th{padding:.6rem;border-bottom:1px solid #354047;text-align:left;word-break:break-all}small{color:#b8c5cb}</style>
<h1>Comma File Portal</h1><p>Local, read-only copy tool. Enter the comma's private IP or a MAC already visible on this PC's local network.</p>
<input id=\"target\" placeholder=\"10.0.0.18 or AA:BB:CC:DD:EE:FF\" size=\"35\"><button onclick=\"connect()\">Connect</button><button onclick=\"files()\">Refresh files</button><p id=\"status\"></p><table><thead><tr><th>File</th><th>Modified</th><th>Size</th><th></th></tr></thead><tbody id=\"files\"></tbody></table>
<script>const status=document.querySelector('#status'),body=document.querySelector('#files');const fmt=n=>new Date(n*1000).toLocaleString();const size=n=>n>1048576?(n/1048576).toFixed(1)+' MB':(n/1024).toFixed(1)+' KB';async function call(path,data){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data||{})});const j=await r.json();if(!r.ok)throw Error(j.error);return j}async function connect(){try{const j=await call('/api/connect',{target:document.querySelector('#target').value});status.textContent='Connected: '+j.serial;await files()}catch(e){status.textContent=e.message}}async function files(){try{const j=await call('/api/files');body.replaceChildren(...j.files.map(f=>{const tr=document.createElement('tr');tr.innerHTML='<td></td><td></td><td></td><td></td>';tr.children[0].textContent=f.path;tr.children[1].textContent=fmt(f.modified_unix);tr.children[2].textContent=size(f.size_bytes);const b=document.createElement('button');b.textContent='Copy';b.onclick=()=>copy(f.identifier);tr.children[3].append(b);return tr}));status.textContent=j.files.length+' recording files found'}catch(e){status.textContent=e.message}}async function copy(id){try{const j=await call('/api/copy',{id});status.textContent='Copied to '+j.destination}catch(e){status.textContent=e.message}}</script>"""


class PortalHandler(BaseHTTPRequestHandler):
  state: PortalState

  def log_message(self, _format: str, *_args: Any) -> None:
    pass

  def _send(self, status: HTTPStatus, value: dict[str, Any], content_type: str = "application/json") -> None:
    payload = json.dumps(value).encode()
    self.send_response(status)
    self.send_header("Content-Type", f"{content_type}; charset=utf-8")
    self.send_header("Content-Length", str(len(payload)))
    self.end_headers()
    self.wfile.write(payload)

  def do_GET(self) -> None:
    if urlparse(self.path).path != "/":
      self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
      return
    payload = PAGE.encode()
    self.send_response(HTTPStatus.OK)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(payload)))
    self.end_headers()
    self.wfile.write(payload)

  def do_POST(self) -> None:
    routes = {"/api/connect": self._connect, "/api/files": self._files, "/api/copy": self._copy}
    handler = routes.get(urlparse(self.path).path)
    if handler is None:
      self._send(HTTPStatus.NOT_FOUND, {"error": "Not found"})
      return
    try:
      length = int(self.headers.get("Content-Length", "0"))
      data = json.loads(self.rfile.read(length) or b"{}")
      if not isinstance(data, dict):
        raise PortalError("Invalid request.")
      with self.state.lock:
        self._send(HTTPStatus.OK, handler(data))
    except (PortalError, importer.ImportFailure, ValueError, OSError, json.JSONDecodeError) as error:
      self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})

  def _connect(self, data: dict[str, Any]) -> dict[str, str]:
    return self.state.connect(str(data.get("target", "")))

  def _files(self, _data: dict[str, Any]) -> dict[str, Any]:
    return {"files": [asdict(item) for item in self.state.list_files()]}

  def _copy(self, data: dict[str, Any]) -> dict[str, str]:
    return {"destination": str(self.state.copy_file(str(data.get("id", ""))))}


def main() -> None:
  parser = argparse.ArgumentParser(description="Run the local comma recording-file portal")
  parser.add_argument("--port", type=int, default=PORTAL_PORT)
  parser.add_argument("--destination", type=Path, default=importer.default_destination() / "Portal downloads")
  parser.add_argument("--adb", type=Path)
  args = parser.parse_args()
  PortalHandler.state = PortalState(args.destination, args.adb)
  server = ThreadingHTTPServer((PORTAL_HOST, args.port), PortalHandler)
  print(f"Open http://{PORTAL_HOST}:{args.port} in this PC's browser")
  try:
    server.serve_forever()
  except KeyboardInterrupt:
    pass
  finally:
    server.server_close()


if __name__ == "__main__":
  main()
