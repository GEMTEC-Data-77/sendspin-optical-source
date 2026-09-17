# Changelog

## 0.3.1

- Added the app homepage URL so Home Assistant's "Visit the Sendspin Optical Source page for more details" link opens the GitHub repository.
- Changed the app README link to an absolute GitHub URL so it works correctly when rendered inside Home Assistant.

## 0.3.0

- First GitHub repository-packaged stable release.
- Removed the experimental stage designation.
- Set the tested jitter-buffer default to 100 ms.
- Added repository metadata, MIT licensing, and public-facing documentation.
- Retained configurable capture latency, process interval, jitter buffer, maximum buffer, log level, and diagnostics.

## 0.2.0

- Established stable operational logging defaults.
- Made jitter-buffer and capture timing settings configurable from the Home Assistant App UI.
- Defaulted detailed audio diagnostics to off.
- Rate-limited repetitive underrun/overrun warnings.
- Retained startup session separators for easier log review.

## 0.1.5

- Added low-latency `parec` capture settings.
- Fixed bursty producer behavior that caused jitter-buffer overrun/underrun cycles.

## 0.1.4

- Added PCM jitter buffering and fixed-duration Sendspin packets.

## 0.1.3

- Corrected Sendspin source timestamp generation using a continuous PCM frame timeline.

## 0.1.2

- Added detailed PCM capture diagnostics.

## 0.1.1

- Updated pairing support for the current `aiosendspin` API.

## 0.1.0

- Initial Home Assistant OS App prototype.
