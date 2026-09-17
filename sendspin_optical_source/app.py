#!/usr/bin/env python3
"""Home Assistant OS PulseAudio -> Sendspin source@v1 bridge."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import math
import struct
import time
from contextlib import suppress
from pathlib import Path

from aiohttp import web
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf

from aiosendspin.client.client import SendspinClient
from aiosendspin.client.models import PairingSupport
from aiosendspin.models.player import SupportedAudioFormat
from aiosendspin.models.source import ClientHelloSourceFeatures, ClientHelloSourceSupport
from aiosendspin.models.types import AudioCodec, Roles
from aiosendspin.noise.keys import Identity
from aiosendspin.noise.trust_store import FileClientPairingStore

SOURCE_NAME = os.getenv("SOURCE_NAME", "Optical Input")
PULSE_SOURCE_MATCH = os.getenv("PULSE_SOURCE_MATCH", "Cubilux")
SAMPLE_RATE = int(os.getenv("SAMPLE_RATE", "48000"))
CHANNELS = int(os.getenv("CHANNELS", "2"))
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8930"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
LIST_SOURCES_ONLY = os.getenv("LIST_SOURCES_ONLY", "false").lower() == "true"
AUDIO_DIAGNOSTICS = os.getenv("AUDIO_DIAGNOSTICS", "false").lower() == "true"
JITTER_BUFFER_MS = int(os.getenv("JITTER_BUFFER_MS", "100"))
MAX_BUFFER_MS = int(os.getenv("MAX_BUFFER_MS", "500"))
CAPTURE_LATENCY_MS = int(os.getenv("CAPTURE_LATENCY_MS", "40"))
CAPTURE_PROCESS_MS = int(os.getenv("CAPTURE_PROCESS_MS", "20"))

DATA_DIR = Path("/data")
IDENTITY_FILE = DATA_DIR / "identity.key"
PAIRING_FILE = DATA_DIR / "pairing.json"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
_LOGGER = logging.getLogger("sendspin-optical-source")


def _local_ipv4() -> str:
    """Best-effort LAN IPv4 address for mDNS advertisement."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


async def _pulse_sources() -> list[tuple[str, str]]:
    """Return [(pulse_name, description), ...]."""
    proc = await asyncio.create_subprocess_exec(
        "pactl",
        "list",
        "short",
        "sources",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"pactl failed: {stderr.decode(errors='replace').strip()}")

    rows: list[tuple[str, str]] = []
    for raw in stdout.decode(errors="replace").splitlines():
        fields = raw.split("\t")
        if len(fields) >= 2:
            pulse_name = fields[1].strip()
            # The short list normally does not include a friendly description.
            rows.append((pulse_name, pulse_name))
    return rows


async def _pulse_descriptions() -> dict[str, str]:
    """Map PulseAudio source names to descriptions using pactl's JSON output when available."""
    proc = await asyncio.create_subprocess_exec(
        "pactl",
        "-f",
        "json",
        "list",
        "sources",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await proc.communicate()
    if proc.returncode != 0:
        return {}
    try:
        import json

        data = json.loads(stdout)
    except Exception:
        return {}

    result: dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            desc = str(item.get("description", name))
            if name:
                result[name] = desc
    return result


async def log_pulse_source_details(source_name: str) -> None:
    """Log mute, volume, state, and sample spec for the selected PulseAudio source."""
    proc = await asyncio.create_subprocess_exec(
        "pactl", "-f", "json", "list", "sources",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return
    try:
        import json
        data = json.loads(stdout)
    except Exception:
        return
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or item.get("name") != source_name:
            continue
        _LOGGER.info("Selected source state: %s", item.get("state", "unknown"))
        _LOGGER.info("Selected source mute: %s", item.get("mute", "unknown"))
        _LOGGER.info("Selected source sample spec: %s", item.get("sample_specification", item.get("sample_spec", "unknown")))
        _LOGGER.info("Selected source channel map: %s", item.get("channel_map", "unknown"))
        volume = item.get("volume")
        if volume is not None:
            _LOGGER.info("Selected source volume: %s", volume)
        return


def pcm_levels_s16le(data: bytes) -> tuple[float, float]:
    """Return (RMS dBFS, peak dBFS) for signed 16-bit little-endian PCM."""
    n = len(data) // 2
    if n <= 0:
        return -120.0, -120.0
    samples = struct.unpack(f"<{n}h", data[: n * 2])
    peak = max(abs(x) for x in samples)
    if peak == 0:
        return -120.0, -120.0
    mean_sq = sum(float(x) * float(x) for x in samples) / n
    rms = math.sqrt(mean_sq)
    rms_db = 20.0 * math.log10(max(rms, 1.0) / 32768.0)
    peak_db = 20.0 * math.log10(max(float(peak), 1.0) / 32768.0)
    return max(rms_db, -120.0), max(peak_db, -120.0)


async def choose_pulse_source(match: str) -> str:
    sources = await _pulse_sources()
    descriptions = await _pulse_descriptions()
    if not sources:
        raise RuntimeError("No PulseAudio capture sources were found")

    _LOGGER.info("Available PulseAudio capture sources:")
    for name, _ in sources:
        _LOGGER.info("  %s  --  %s", name, descriptions.get(name, name))

    needle = match.casefold().strip()
    if not needle:
        if len(sources) == 1:
            return sources[0][0]
        raise RuntimeError(
            "pulse_source_match is blank and more than one capture source exists; "
            "set it to part of the Cubilux source name/description"
        )

    hits: list[str] = []
    for name, _ in sources:
        haystack = f"{name} {descriptions.get(name, '')}".casefold()
        if needle in haystack:
            hits.append(name)

    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise RuntimeError(
            f"No PulseAudio source matched {match!r}. Check the app log for the available names."
        )
    raise RuntimeError(
        f"More than one PulseAudio source matched {match!r}: {hits}. "
        "Use a more specific pulse_source_match."
    )


def load_or_create_identity() -> Identity:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if IDENTITY_FILE.exists():
        raw = IDENTITY_FILE.read_bytes()
        return Identity.from_private_bytes(raw)

    identity = Identity.generate()
    tmp = IDENTITY_FILE.with_suffix(".tmp")
    tmp.write_bytes(identity.private_bytes)
    os.chmod(tmp, 0o600)
    tmp.replace(IDENTITY_FILE)
    return identity


class OpticalSourceBridge:
    def __init__(self, pulse_source: str) -> None:
        self.pulse_source = pulse_source
        self.client: SendspinClient | None = None
        self.capture = None
        self.capture_task: asyncio.Task[None] | None = None
        self.parec: asyncio.subprocess.Process | None = None
        self.stop_lock = asyncio.Lock()
        self.total_audio_bytes = 0
        self.total_chunks = 0
        self.last_diag_log = 0.0
        self.capture_anchor_us: int | None = None
        self.frames_sent = 0
        self.queue: asyncio.Queue[tuple[int, bytes]] | None = None
        self.buffer_underruns = 0
        self.buffer_overruns = 0
        self.last_overrun_warning = 0.0
        self.last_underrun_warning = 0.0
        self.dropped_packets = 0

    async def initialize(self) -> None:
        identity = load_or_create_identity()
        pairing_store = await FileClientPairingStore.open(PAIRING_FILE)

        async def pairing_code_display(code: str | None) -> None:
            if code:
                _LOGGER.warning("============================================================")
                _LOGGER.warning("SENDSPIN PAIRING CODE: %s", code)
                _LOGGER.warning("Enter this code in Music Assistant when prompted.")
                _LOGGER.warning("============================================================")
            else:
                _LOGGER.info("Sendspin pairing-code display cleared")

        async def gesture_prompt(active: bool) -> None:
            if active:
                _LOGGER.warning(
                    "Pairing approval is waiting for a pairing window. Restart this app, "
                    "then try pairing again; the window will be opened automatically at startup."
                )

        pairing_support = PairingSupport(
            gesture_prompt=gesture_prompt,
            pin_display=pairing_code_display,
            offer_static_pin=False,
        )

        self.client = SendspinClient(
            identity=identity,
            client_name=SOURCE_NAME,
            roles=[Roles.SOURCE],
            pairing_store=pairing_store,
            source_support=ClientHelloSourceSupport(
                features=ClientHelloSourceFeatures(line_sense=False)
            ),
            pairing_support=pairing_support,
        )
        # This makes gesture-gated pairing possible immediately as well.
        self.client.open_pairing_window()
        self.client.add_server_command_listener(self._on_server_command)
        self.client.add_disconnect_listener(self._on_disconnect)
        _LOGGER.info("Sendspin client ID: %s", identity.peer_id)

    def _on_server_command(self, payload) -> None:
        source = getattr(payload, "source", None)
        if source is None:
            return
        command = getattr(source, "command", None)
        _LOGGER.info("Music Assistant source command: %s", command)
        if command == "start":
            asyncio.create_task(self.start_capture())
        elif command == "stop":
            asyncio.create_task(self.stop_capture())

    def _on_disconnect(self) -> None:
        _LOGGER.warning("Music Assistant disconnected")
        asyncio.create_task(self.stop_capture())

    async def start_capture(self) -> None:
        if self.client is None or not self.client.connected:
            _LOGGER.warning("Ignoring start request because Sendspin is not connected")
            return
        if self.capture_task is not None and not self.capture_task.done():
            return

        # SourceCapture.start() requires Sendspin clock synchronization.
        for _ in range(100):
            if self.client.is_time_synchronized():
                break
            await asyncio.sleep(0.05)
        else:
            _LOGGER.error("Sendspin clock did not synchronize; cannot start source stream")
            return

        fmt = SupportedAudioFormat(
            codec=AudioCodec.PCM,
            channels=CHANNELS,
            sample_rate=SAMPLE_RATE,
            bit_depth=16,
        )
        self.capture = self.client.create_source_capture(fmt)
        await self.capture.start()
        self.capture_anchor_us = None
        self.frames_sent = 0
        self.total_audio_bytes = 0
        self.total_chunks = 0
        self.last_diag_log = 0.0
        self.buffer_underruns = 0
        self.buffer_overruns = 0
        self.dropped_packets = 0
        self.last_overrun_warning = 0.0
        self.last_underrun_warning = 0.0
        _LOGGER.info("Sendspin client_stream/start sent: pcm, %d Hz, 16-bit, %d channel(s)", SAMPLE_RATE, CHANNELS)
        if AUDIO_DIAGNOSTICS:
            await log_pulse_source_details(self.pulse_source)

        cmd = [
            "parec",
            f"--device={self.pulse_source}",
            "--raw",
            "--format=s16le",
            f"--rate={SAMPLE_RATE}",
            f"--channels={CHANNELS}",
            f"--latency-msec={CAPTURE_LATENCY_MS}",
            f"--process-time-msec={CAPTURE_PROCESS_MS}",
        ]
        _LOGGER.info("Starting capture: %s", " ".join(cmd))
        self.parec = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.capture_task = asyncio.create_task(self._capture_loop())
        _LOGGER.info("Optical source stream started")

    async def _capture_loop(self) -> None:
        """Capture continuously into a small jitter buffer and transmit at a fixed cadence."""
        assert self.client is not None
        assert self.capture is not None
        assert self.parec is not None
        assert self.parec.stdout is not None

        bytes_per_frame = CHANNELS * 2
        frames_per_packet = max(1, SAMPLE_RATE // 50)  # 20 ms
        packet_bytes = frames_per_packet * bytes_per_frame
        packet_duration_us = frames_per_packet * 1_000_000 // SAMPLE_RATE
        startup_packets = max(1, round(JITTER_BUFFER_MS / 20))
        max_packets = max(startup_packets + 2, round(MAX_BUFFER_MS / 20))
        self.queue = asyncio.Queue(maxsize=max_packets)
        self.buffer_underruns = 0
        self.buffer_overruns = 0
        self.dropped_packets = 0

        _LOGGER.info(
            "PCM jitter buffer: packet=%d bytes/%d frames/%d ms startup=%d packets (%d ms) max=%d packets (%d ms)",
            packet_bytes, frames_per_packet, packet_duration_us // 1000,
            startup_packets, startup_packets * 20, max_packets, max_packets * 20,
        )

        async def producer() -> None:
            pending = bytearray()
            packet_index = 0
            while True:
                # Read generously; PulseAudio may deliver bursty blocks. We re-packetize
                # into exact 20 ms PCM packets before they enter the jitter buffer.
                data = await self.parec.stdout.read(packet_bytes * 4)
                if not data:
                    rc = await self.parec.wait()
                    stderr = b""
                    if self.parec.stderr is not None:
                        stderr = await self.parec.stderr.read()
                    raise RuntimeError(
                        f"parec exited with code {rc}: {stderr.decode(errors='replace').strip()}"
                    )
                pending.extend(data)

                while len(pending) >= packet_bytes:
                    packet = bytes(pending[:packet_bytes])
                    del pending[:packet_bytes]
                    start_frame = packet_index * frames_per_packet
                    packet_index += 1

                    if self.queue.full():
                        try:
                            self.queue.get_nowait()
                            self.queue.task_done()
                            self.buffer_overruns += 1
                            self.dropped_packets += 1
                            now = time.monotonic()
                            if now - self.last_overrun_warning >= 10.0:
                                _LOGGER.warning(
                                    "PCM jitter buffer overrun: dropped oldest packet (total overruns=%d, queue=%d/%d)",
                                    self.buffer_overruns, self.queue.qsize(), max_packets,
                                )
                                self.last_overrun_warning = now
                        except asyncio.QueueEmpty:
                            pass
                    self.queue.put_nowait((start_frame, packet))
                    # Give the sender a chance to run even if parec hands us a burst.
                    await asyncio.sleep(0)

        async def sender() -> None:
            # Build the startup cushion before feeding Sendspin. This absorbs the
            # bursty delivery we observed from parec/PulseAudio.
            while self.queue.qsize() < startup_packets:
                await asyncio.sleep(0.005)

            # The oldest queued packet was captured approximately one buffered
            # duration ago. Anchor its source timestamp to the synchronized
            # Sendspin clock, then derive every later packet timestamp from its
            # exact sample-frame position.
            first_frame, first_packet = await self.queue.get()
            self.queue.task_done()
            buffered_packets = self.queue.qsize() + 1
            self.capture_anchor_us = (
                self.client.now_us()
                - (buffered_packets * packet_duration_us)
                - (first_frame * 1_000_000 // SAMPLE_RATE)
            )
            _LOGGER.info(
                "Sendspin PCM timeline anchored at %d us with %d buffered packets (~%d ms)",
                self.capture_anchor_us, buffered_packets, buffered_packets * 20,
            )

            loop = asyncio.get_running_loop()
            next_send = loop.time()
            current: tuple[int, bytes] | None = (first_frame, first_packet)

            while True:
                if current is None:
                    try:
                        current = await asyncio.wait_for(self.queue.get(), timeout=0.060)
                        self.queue.task_done()
                    except asyncio.TimeoutError:
                        self.buffer_underruns += 1
                        now = time.monotonic()
                        if now - self.last_underrun_warning >= 10.0:
                            _LOGGER.warning(
                                "PCM jitter buffer underrun: no packet available (total underruns=%d)",
                                self.buffer_underruns,
                            )
                            self.last_underrun_warning = now
                        # Re-base pacing after a real starvation event instead of
                        # trying to catch up in a burst. Packet timestamps remain
                        # tied to capture frame positions.
                        next_send = loop.time()
                        continue

                start_frame, packet = current
                current = None
                first_sample_us = (
                    self.capture_anchor_us
                    + (start_frame * 1_000_000 // SAMPLE_RATE)
                )
                await self.capture.feed(packet, capture_timestamp_us=first_sample_us)
                self.frames_sent += frames_per_packet
                self.total_audio_bytes += len(packet)
                self.total_chunks += 1

                if AUDIO_DIAGNOSTICS:
                    now = time.monotonic()
                    if now - self.last_diag_log >= 2.0:
                        rms_db, peak_db = pcm_levels_s16le(packet)
                        _LOGGER.debug(
                            "Audio diagnostic: chunks=%d bytes=%d frames_sent=%d queue=%d/%d (~%d ms) underruns=%d overruns=%d dropped=%d RMS=%.1f dBFS peak=%.1f dBFS ts=%d us",
                            self.total_chunks, self.total_audio_bytes, self.frames_sent,
                            self.queue.qsize(), max_packets, self.queue.qsize() * 20,
                            self.buffer_underruns, self.buffer_overruns, self.dropped_packets,
                            rms_db, peak_db, first_sample_us,
                        )
                        if peak_db <= -119.0:
                            _LOGGER.warning(
                                "Captured PCM is digital silence (all zero samples). Check that the optical source is active, set to 2-channel PCM, and the Cubilux has S/PDIF lock."
                            )
                        self.last_diag_log = now

                # Pace transmission at one exact 20 ms packet interval. We use
                # monotonic time only for delivery cadence; Sendspin timestamps
                # remain derived from PCM frame positions.
                next_send += packet_duration_us / 1_000_000.0
                delay = next_send - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                elif delay < -0.100:
                    _LOGGER.warning(
                        "PCM sender is %.0f ms behind schedule; rebasing send cadence",
                        -delay * 1000.0,
                    )
                    next_send = loop.time()

                if self.queue.empty():
                    self.buffer_underruns += 1
                    now = time.monotonic()
                    if now - self.last_underrun_warning >= 10.0:
                        _LOGGER.warning(
                            "PCM jitter buffer low/empty after send (total underruns=%d)",
                            self.buffer_underruns,
                        )
                        self.last_underrun_warning = now

                try:
                    current = self.queue.get_nowait()
                    self.queue.task_done()
                except asyncio.QueueEmpty:
                    current = None

        producer_task = asyncio.create_task(producer(), name="pcm-producer")
        sender_task = asyncio.create_task(sender(), name="pcm-sender")
        try:
            done, pending = await asyncio.wait(
                {producer_task, sender_task},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc
            # Neither task should normally return.
            raise RuntimeError("PCM producer/sender stopped unexpectedly")
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Audio capture/stream loop failed")
        finally:
            for task in (producer_task, sender_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(producer_task, sender_task, return_exceptions=True)
            if self.capture_task is asyncio.current_task():
                self.capture_task = None
            if self.parec is not None and self.parec.returncode is None:
                self.parec.terminate()
                with suppress(ProcessLookupError, asyncio.TimeoutError):
                    await asyncio.wait_for(self.parec.wait(), timeout=2)
            self.parec = None
            if self.capture is not None:
                with suppress(Exception):
                    await self.capture.stop()
            self.capture = None
            self.queue = None

    async def stop_capture(self) -> None:
        async with self.stop_lock:
            task = self.capture_task
            self.capture_task = None
            if task is not None and task is not asyncio.current_task() and not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

            if self.parec is not None and self.parec.returncode is None:
                self.parec.terminate()
                with suppress(Exception):
                    await asyncio.wait_for(self.parec.wait(), timeout=2)
            self.parec = None

            if self.capture is not None:
                with suppress(Exception):
                    await self.capture.stop()
            self.capture = None
            _LOGGER.info("Optical source stream stopped (chunks=%d, bytes=%d)", self.total_chunks, self.total_audio_bytes)

    async def websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        if self.client is None:
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        _LOGGER.info("Incoming Sendspin connection from %s", request.remote)
        await self.client.attach_websocket(ws)
        return ws


async def main() -> None:
    pulse_source = await choose_pulse_source(PULSE_SOURCE_MATCH)
    _LOGGER.info("Selected PulseAudio source: %s", pulse_source)

    if LIST_SOURCES_ONLY:
        _LOGGER.info("list_sources_only=true: source enumeration complete; exiting")
        return

    bridge = OpticalSourceBridge(pulse_source)
    await bridge.initialize()

    app = web.Application()
    app.router.add_get("/sendspin", bridge.websocket_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", LISTEN_PORT)
    await site.start()

    lan_ip = _local_ipv4()
    service_type = "_sendspin._tcp.local."
    service_name = f"{SOURCE_NAME}.{service_type}"
    info = AsyncServiceInfo(
        service_type,
        service_name,
        addresses=[socket.inet_aton(lan_ip)] if lan_ip != "127.0.0.1" else [],
        port=LISTEN_PORT,
        properties={b"path": b"/sendspin", b"name": SOURCE_NAME.encode("utf-8")},
        server=f"sendspin-optical-{bridge.client.identity.peer_id[:8].lower()}.local.",
    )
    azc = AsyncZeroconf()
    try:
        await azc.async_register_service(info)
        _LOGGER.info(
            "Advertising %s via mDNS at ws://%s:%d/sendspin",
            SOURCE_NAME,
            lan_ip,
            LISTEN_PORT,
        )
        _LOGGER.info("Waiting for Music Assistant discovery/pairing...")
        await asyncio.Event().wait()
    finally:
        with suppress(Exception):
            await bridge.stop_capture()
        if bridge.client is not None:
            with suppress(Exception):
                await bridge.client.disconnect()
        with suppress(Exception):
            await azc.async_unregister_service(info)
        await azc.async_close()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        _LOGGER.exception("Fatal error")
        raise
