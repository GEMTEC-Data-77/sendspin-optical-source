# Sendspin Optical Source for Home Assistant

A Home Assistant OS App that publishes a PulseAudio capture source as a paired **Sendspin `source@v1` Live Input** for Music Assistant.

It was developed and tested with a Cubilux USB-C optical S/PDIF capture adapter, but the capture-source matching is generic and may work with other PulseAudio input devices.

## Signal path

```text
Optical S/PDIF source
        ↓
USB audio capture device
        ↓
Home Assistant OS / PulseAudio
        ↓
Sendspin Optical Source
        ↓
Music Assistant / Sendspin Source
        ↓
Music Assistant player or group
```

## Current status

Version **0.3.0** is the first repository-packaged stable release. The underlying 0.2.x build has been used successfully for multi-day playback testing.

Known-good test configuration:

- 48 kHz
- 16-bit PCM
- stereo
- 40 ms PulseAudio capture latency
- 20 ms capture processing interval
- 100 ms Sendspin jitter buffer

The app currently expects decoded PCM audio. Configure the optical source device for stereo PCM rather than Dolby Digital, DTS, AC-3, or another encoded bitstream.

## Requirements

- Home Assistant OS / Supervisor with Apps support
- Music Assistant with the Sendspin Source plugin enabled
- A PulseAudio-visible audio capture device
- `amd64` or `aarch64` Home Assistant host

## Installation

### From this repository

1. In Home Assistant, open **Settings → Apps → App store**.
2. Open the repository management menu.
3. Add this repository URL: `https://github.com/GEMTEC-Data-77/sendspin-optical-source`
4. Refresh the App store.
5. Install **Sendspin Optical Source**.
6. Review the App configuration and start it.
7. In Music Assistant, adopt/pair the discovered Sendspin source when prompted.
8. Enter the pairing PIN printed in the App log.
9. In Music Assistant, select a destination player/group and open **Browse** to select the Live Input.

> Note: if this GitHub repository is private, Home Assistant repository installation may require additional authentication or may not work through the normal repository URL flow. The same App can still be installed locally under `/addons/sendspin_optical_source`.

## Configuration

| Option | Default | Purpose |
|---|---:|---|
| `source_name` | `Optical Input` | Name advertised to Music Assistant |
| `pulse_source_match` | `Cubilux` | Case-insensitive substring used to select the PulseAudio source |
| `sample_rate` | `48000` | PCM sample rate |
| `channels` | `2` | Number of PCM channels |
| `listen_port` | `8930` | Sendspin WebSocket listener port |
| `log_level` | `info` | `debug`, `info`, `warning`, or `error` |
| `list_sources_only` | `false` | List PulseAudio capture sources and exit |
| `audio_diagnostics` | `false` | Enable detailed PCM diagnostics |
| `jitter_buffer_ms` | `100` | Startup/target jitter buffer |
| `max_buffer_ms` | `500` | Maximum PCM queue depth |
| `capture_latency_ms` | `40` | PulseAudio/parec requested capture latency |
| `capture_process_ms` | `20` | PulseAudio/parec processing interval |

Changes to these options require only **Save + Restart**; the App does not need to be rebuilt.

## Finding the correct PulseAudio source

If the default `Cubilux` match does not select your device:

1. Set `list_sources_only: true`.
2. Start the App and inspect its log.
3. Note the desired PulseAudio source name or description.
4. Set `list_sources_only: false`.
5. Change `pulse_source_match` to a unique substring from that source.
6. Restart the App.

## Pairing and persistent identity

The App generates a Sendspin identity and stores it, along with pairing state, under Home Assistant's persistent `/data` App storage. Restarting the App or Home Assistant should therefore preserve the paired identity.

Do **not** publish or copy runtime `identity.key` or `pairing.json` files into this repository.

## Troubleshooting

For normal operation, leave `log_level: info` and `audio_diagnostics: false`.

For detailed troubleshooting, temporarily use:

```yaml
log_level: debug
audio_diagnostics: true
```

The App logs a clear session separator at startup. Diagnostic mode reports buffer state, PCM levels, underruns, and overruns.

If audio cuts in and out, first check for jitter-buffer underruns/overruns. The low-latency capture settings are important: earlier builds allowed `parec` to deliver large bursts, which caused alternating queue overruns and starvation.

## License

MIT License. See [LICENSE](LICENSE).
