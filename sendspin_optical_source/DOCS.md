# Sendspin Optical Source

This App captures PCM audio from a Home Assistant OS PulseAudio input and exposes it to Music Assistant as a paired Sendspin `source@v1` Live Input.

## Recommended starting configuration

```yaml
source_name: "Optical Input"
pulse_source_match: "Cubilux"
sample_rate: 48000
channels: 2
listen_port: 8930
log_level: "info"
list_sources_only: false
audio_diagnostics: false
jitter_buffer_ms: 100
max_buffer_ms: 500
capture_latency_ms: 40
capture_process_ms: 20
```

The Cubilux match is the tested default, but another PulseAudio capture device can be selected by changing `pulse_source_match`.

## Pairing

When Music Assistant discovers the source and pairing begins, the App prints the Sendspin pairing code in its log. Enter that code in Music Assistant when prompted.

The Sendspin identity and pairing database are stored in persistent `/data` App storage, so pairing should survive App restarts and Home Assistant reboots.

## Playback

After pairing, Music Assistant exposes the source as a Live Input. Select a destination player/group, open **Browse**, select the Live Input, and start playback. Capture begins only after Music Assistant sends the Sendspin source `start` command.

The tested format is 48 kHz, 16-bit stereo PCM. Configure optical sources for stereo PCM rather than Dolby Digital, DTS, AC-3, or another encoded bitstream.

## Buffer tuning

`jitter_buffer_ms` is configurable without rebuilding the App. A value of **100 ms** is the current tested baseline. Lower values can reduce latency but may increase sensitivity to scheduling jitter. If underruns occur, increase the value.

`capture_latency_ms: 40` and `capture_process_ms: 20` are known-good settings that prevent the large PulseAudio/`parec` delivery bursts observed during early testing.

## Diagnostics

For routine use:

```yaml
log_level: info
audio_diagnostics: false
```

For troubleshooting:

```yaml
log_level: debug
audio_diagnostics: true
```

Detailed diagnostics report PCM levels, queue depth, underruns, and overruns. Warning messages are rate-limited to keep normal logs readable.
