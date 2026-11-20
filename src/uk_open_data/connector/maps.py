"""The map of an analysis result as a picture for the person in a chat.

An analysis result describes a map and holds the table that feeds it, one row per
area. Those rows are left out of an answer, so an assistant cannot draw the
map and is not asked to. The connector draws it here instead, and the picture
travels beside the answer in the part of a tool result that is meant for the
app the person is using and not for the model. An app that supports MCP Apps
shows it with :data:`MAP_VIEW`.
"""

import logging
import queue
import threading
from collections.abc import Callable, Iterable
from typing import Any

import requests

from uk_open_data.analyses import AnalysisResult, load_map_boundaries, render_map
from uk_open_data.connector.privacy import find_row_values

logger = logging.getLogger(__name__)

Boundaries = Callable[[AnalysisResult], dict[str, Any]]
"""Gives the outlines of every area on a result's map, as GeoJSON."""

MAP_VIEW_URI = "ui://kindtech/analysis-map.html"
MAP_META_KEY = "kindtech/map"
# Above this the pictures are not sent: an answer should not carry megabytes.
MAX_PICTURE_BYTES = 1_500_000
# How long an answer waits for the outlines of its map. They usually come in a
# few seconds, but at times the boundary service has taken a minute or more,
# and the figures should not wait that long for a picture.
MAP_SECONDS = 15.0
# Where the code that asks the boundary service logs its own errors.
OUTLINES_LOGGER = "uk_open_data.geo"
LINE_LEFT_OUT = (
    "A line from the code that asks the boundary service is left out here: "
    "it can hold the web address asked."
)

DRAWN = (
    "A map of this result was drawn for the person, coloured by: {layers}. "
    "Where the app they are using shows pictures from this connector, it "
    "appears with this answer. You are not given the picture, so do not "
    "describe what it shows. If the person sees no map, the Kindtech Evidence "
    "page and the command line tool draw the same one."
)
NO_OUTLINES = (
    "No map was drawn, because the outlines of the areas could not be fetched "
    "just now. The figures are not affected. The Kindtech Evidence page and "
    "the command line tool draw the map."
)
TOO_SLOW = (
    "No map was drawn, because the outlines of the areas were slow to arrive "
    "and the figures were not kept waiting. The service that holds them is "
    "slow at times, so it is worth running the analysis again in a few "
    "minutes for the map. The Kindtech Evidence page and the command line "
    "tool draw it too."
)
TOO_LARGE = (
    "No map was drawn, because a picture of this many areas is too large to "
    "send with an answer. The Kindtech Evidence page and the command line tool draw it."
)
WITHHELD = (
    "No map was drawn, because the picture would have repeated a value from the rows."
)


def picture_for(
    result: AnalysisResult,
    guarded: Iterable[object] = (),
    boundaries: Boundaries | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Draw every layer of a result's map, for the person and not the model.

    Args:
        result: An analysis result, with the rows of its detail tables.
        guarded: Values from the input rows that the picture must not repeat.
        boundaries: Gives the outlines of the areas. Left out, the quick
            outlines, simplified to 200 metres, are fetched from the ONS Open
            Geography Portal by public area code.

    Returns:
        The picture, as ``{"title": ..., "layers": [{"id", "label", "svg"}]}``
        or ``None`` when there is none to show, then a note for the assistant
        that says a map was drawn or why not. The note is empty when the analysis
        has no map.
    """
    if result.map is None:
        return None, ""
    try:
        outlines = _in_time(boundaries or _quick_outlines, result)
        layers = [
            {
                "id": layer.id,
                "label": layer.label,
                "svg": render_map(result, layer.id, outlines),
            }
            for layer in result.map.layers
        ]
    except TimeoutError:
        logger.warning("A map was not drawn: its outlines took too long.")
        return None, TOO_SLOW
    except (requests.RequestException, ValueError) as error:
        # The error text can hold a web address, so only its kind is logged.
        logger.warning("A map could not be drawn: %s", type(error).__name__)
        return None, NO_OUTLINES
    layers = _that_fit(layers)
    if not layers:
        return None, TOO_LARGE
    if find_row_values(layers, guarded):
        logger.warning("A map was withheld because it repeated an input value.")
        return None, WITHHELD
    labels = ", ".join(layer["label"] for layer in layers)
    picture = {"title": result.map.title, "layers": layers}
    return picture, DRAWN.format(layers=labels)


def keep_addresses_out_of_the_log() -> None:
    """Replace what the boundary service's code logs with one plain sentence.

    That code logs a failed request with the web address it asked, which holds
    the area codes of the map. A program that owns its log calls this once, as
    the connector's command does. Each warning or error from that code then
    becomes :data:`LINE_LEFT_OUT` at the same level, and its quieter lines are
    dropped. Calling it again changes nothing.
    """
    outlines_log = logging.getLogger(OUTLINES_LOGGER)
    outlines_log.propagate = False
    if not any(isinstance(kept, _PlainLine) for kept in outlines_log.handlers):
        outlines_log.addHandler(_PlainLine(logging.WARNING))


class _PlainLine(logging.Handler):
    """Says that a line was left out, and nothing of what it held."""

    def emit(self, record: logging.LogRecord) -> None:
        logger.log(record.levelno, LINE_LEFT_OUT)


def _quick_outlines(result: AnalysisResult) -> dict[str, Any]:
    """The 200 metre outlines of a result's map, which do not keep a chat waiting."""
    return load_map_boundaries(result, fine=False)


def _in_time(load: Boundaries, result: AnalysisResult) -> dict[str, Any]:
    """The outlines ``load`` gives for a result, or ``TimeoutError`` if it is slow.

    The outlines are fetched on a thread of their own. When they have not come
    within :data:`MAP_SECONDS` the answer goes out without a map and the fetch
    is left to finish, so the outlines the package keeps for the process are
    there for the next map. The thread does not keep the program alive when
    it is told to stop.

    Raises:
        TimeoutError: If the outlines did not arrive in time.
    """
    arrived: queue.Queue[tuple[dict[str, Any] | None, Exception | None]] = queue.Queue(
        maxsize=1
    )

    def fetch() -> None:
        try:
            arrived.put((load(result), None))
        except Exception as error:  # passed on to the caller below
            arrived.put((None, error))

    threading.Thread(target=fetch, name="map-outlines", daemon=True).start()
    try:
        outlines, error = arrived.get(timeout=MAP_SECONDS)
    except queue.Empty:
        raise TimeoutError from None
    if error is not None:
        raise error
    return outlines or {}


def _that_fit(layers: list[dict[str, str]]) -> list[dict[str, str]]:
    """The leading layers whose pictures together stay within the size limit."""
    kept: list[dict[str, str]] = []
    size = 0
    for layer in layers:
        size += len(layer["svg"].encode())
        if size > MAX_PICTURE_BYTES:
            break
        kept.append(layer)
    return kept


# The page an app shows with the answer. It speaks the MCP Apps protocol
# (JSON-RPC over postMessage) with nothing fetched from anywhere: it greets the
# host, waits for the tool result and shows the pictures found under
# MAP_META_KEY. With no picture it says so in one line.
MAP_VIEW = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Map</title>
<style>
  :root { color-scheme: light dark; --ink: #0b0b0b; --ink2: #52514e;
    --line: #c9c8c0; --on: #1c5cab; --on-ink: #ffffff; }
  @media (prefers-color-scheme: dark) {
    :root { --ink: #f0efec; --ink2: #c3c2b7; --line: #4a4a46; --on: #86b6ef;
      --on-ink: #0b0b0b; }
  }
  html, body { margin: 0; background: transparent; }
  body { padding: 4px 0; color: var(--ink);
    font: 14px/1.4 system-ui, -apple-system, 'Segoe UI', sans-serif; }
  #layers { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 8px; }
  #layers[hidden] { display: none; }
  #layers button { font: inherit; color: var(--ink); background: transparent;
    border: 1px solid var(--line); border-radius: 6px; padding: 4px 10px;
    cursor: pointer; }
  #layers button[aria-pressed="true"] { background: var(--on);
    border-color: var(--on); color: var(--on-ink); }
  #layers button:focus-visible { outline: 2px solid var(--on);
    outline-offset: 2px; }
  #map svg { display: block; width: 100%; height: auto; max-width: 720px;
    border-radius: 6px; }
  #note { margin: 0; color: var(--ink2); font-size: 13px; }
</style>
</head>
<body>
<div id="layers" role="group" aria-label="What the map is coloured by" hidden></div>
<div id="map"></div>
<p id="note">Waiting for the result.</p>
<script>
(() => {
  const KEY = "kindtech/map";
  const layers = document.getElementById("layers");
  const map = document.getElementById("map");
  const note = document.getElementById("note");
  const waiting = new Map();
  let nextId = 1;

  const send = (message) =>
    window.parent.postMessage({ jsonrpc: "2.0", ...message }, "*");
  const request = (method, params) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      waiting.set(id, { resolve, reject });
      send({ id, method, params });
    });

  const say = (text) => {
    layers.hidden = true;
    map.replaceChildren();
    note.textContent = text;
    note.hidden = false;
  };

  const draw = (picture, chosen) => {
    // The picture is SVG text made by the connector. It is read as a picture,
    // not as a page, and anything that could run is taken out before it is
    // shown.
    const parsed = new DOMParser().parseFromString(chosen.svg, "image/svg+xml");
    const svg = parsed.documentElement;
    if (svg.nodeName !== "svg") return say("The map could not be shown.");
    svg.querySelectorAll("script, foreignObject").forEach((node) => node.remove());
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    map.replaceChildren(document.importNode(svg, true));
    for (const button of layers.children) {
      button.setAttribute("aria-pressed", String(button.dataset.layer === chosen.id));
    }
  };

  const show = (result) => {
    const picture = result && result._meta && result._meta[KEY];
    if (!picture || !Array.isArray(picture.layers) || !picture.layers.length) {
      return say("There is no map with this answer.");
    }
    layers.replaceChildren(
      ...picture.layers.map((layer) => {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.layer = layer.id;
        button.textContent = layer.label;
        button.addEventListener("click", () => draw(picture, layer));
        return button;
      }),
    );
    layers.hidden = picture.layers.length < 2;
    note.hidden = true;
    draw(picture, picture.layers[0]);
  };

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (!message || message.jsonrpc !== "2.0") return;
    if (message.method === undefined) {
      const asked = waiting.get(message.id);
      if (!asked) return;
      waiting.delete(message.id);
      if (message.error) asked.reject(message.error);
      else asked.resolve(message.result);
    } else if (message.method === "ui/notifications/tool-result") {
      show(message.params);
    } else if (message.method === "ui/notifications/tool-cancelled") {
      say("The run was stopped, so there is no map.");
    } else if (message.id !== undefined) {
      const known = ["ping", "ui/resource-teardown"].includes(message.method);
      const unknown = { code: -32601, message: "Method not found" };
      send(known ? { id: message.id, result: {} } : { id: message.id, error: unknown });
    }
  });

  const reportSize = () =>
    new ResizeObserver(() => {
      const box = document.documentElement.getBoundingClientRect();
      send({
        method: "ui/notifications/size-changed",
        params: { width: Math.ceil(box.width), height: Math.ceil(box.height) },
      });
    }).observe(document.documentElement);

  request("ui/initialize", {
    appInfo: { name: "kindtech-analysis-map", version: "1" },
    appCapabilities: { availableDisplayModes: ["inline"] },
    protocolVersion: "2026-01-26",
  }).then(
    () => {
      send({ method: "ui/notifications/initialized", params: {} });
      reportSize();
    },
    () => say("The map could not be shown here."),
  );
})();
</script>
</body>
</html>
"""
