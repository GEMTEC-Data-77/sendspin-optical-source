#!/usr/bin/with-contenv bashio
set -e

export SOURCE_NAME="$(bashio::config 'source_name')"
export PULSE_SOURCE_MATCH="$(bashio::config 'pulse_source_match')"
export SAMPLE_RATE="$(bashio::config 'sample_rate')"
export CHANNELS="$(bashio::config 'channels')"
export LISTEN_PORT="$(bashio::config 'listen_port')"
export LOG_LEVEL="$(bashio::config 'log_level')"
export LIST_SOURCES_ONLY="$(bashio::config 'list_sources_only')"
export AUDIO_DIAGNOSTICS="$(bashio::config 'audio_diagnostics')"
export JITTER_BUFFER_MS="$(bashio::config 'jitter_buffer_ms')"
export MAX_BUFFER_MS="$(bashio::config 'max_buffer_ms')"
export CAPTURE_LATENCY_MS="$(bashio::config 'capture_latency_ms')"
export CAPTURE_PROCESS_MS="$(bashio::config 'capture_process_ms')"

bashio::log.info "================================================================"
bashio::log.info " SENDSPIN OPTICAL SOURCE — NEW SESSION v0.3.0"
bashio::log.info "================================================================"
bashio::log.info "Starting Sendspin Optical Source"
bashio::log.info "Friendly name: ${SOURCE_NAME}"
bashio::log.info "PulseAudio source match: ${PULSE_SOURCE_MATCH}"
bashio::log.info "PCM format: ${SAMPLE_RATE} Hz, 16-bit, ${CHANNELS} channel(s)"
bashio::log.info "Sendspin listener: TCP ${LISTEN_PORT}, path /sendspin"
bashio::log.info "PCM jitter buffer: ${JITTER_BUFFER_MS} ms startup, ${MAX_BUFFER_MS} ms maximum"
bashio::log.info "PulseAudio capture timing: latency=${CAPTURE_LATENCY_MS} ms, process=${CAPTURE_PROCESS_MS} ms"

exec /opt/sendspin-venv/bin/python /app/app.py
