from pydub import AudioSegment
import io
import time

def mp3_chunks_to_pcm(chunks, min_buffer_size=16384):
    """
    Generator that takes an iterable of MP3 audio chunks (bytes) and yields PCM raw audio data.
    Designed for streaming audio playback with PyAudio.

    Args:
        chunks: Iterable yielding MP3 bytes (e.g., from ElevenLabs streaming API).
        min_buffer_size: Minimum number of bytes to buffer before attempting to decode (increased for better MP3 decoding).

    Yields:
        PCM raw audio bytes suitable for PyAudio playback.
    """
    buffer = io.BytesIO()
    decode_count = 0
    total_input_bytes = 0
    total_output_bytes = 0
    start_time = time.time()

    print(f"[MP3 Decoder] Starting decode with min_buffer_size={min_buffer_size}")

    for chunk in chunks:
        if not chunk:
            continue
        buffer.write(chunk)
        total_input_bytes += len(chunk)

        # Only attempt to decode if we have enough data
        if buffer.tell() < min_buffer_size:
            continue

        buffer.seek(0)
        try:
            decode_start = time.time()
            audio = AudioSegment.from_file(buffer, format="mp3")
            decode_time = time.time() - decode_start
            pcm_data = audio.raw_data
            decode_count += 1
            total_output_bytes += len(pcm_data)

            print(f"[MP3 Decoder] Decode #{decode_count}: {buffer.tell()} bytes -> {len(pcm_data)} PCM bytes ({decode_time:.3f}s)")
            yield pcm_data

            # Reset buffer for next chunk
            buffer = io.BytesIO()
        except Exception as e:
            # Not enough data yet, continue buffering
            print(f"[MP3 Decoder] Decode failed with {buffer.tell()} bytes, continuing to buffer: {e}")
            buffer.seek(0, io.SEEK_END)

    # Try to flush remaining buffer at the end
    buffer.seek(0)
    try:
        if buffer.getbuffer().nbytes > 0:
            decode_start = time.time()
            audio = AudioSegment.from_file(buffer, format="mp3")
            decode_time = time.time() - decode_start
            pcm_data = audio.raw_data
            decode_count += 1
            total_output_bytes += len(pcm_data)
            print(f"[MP3 Decoder] Final decode: {buffer.tell()} bytes -> {len(pcm_data)} PCM bytes ({decode_time:.3f}s)")
            yield pcm_data
    except Exception as e:
        print(f"[MP3 Decoder] Final decode failed: {e}")

    total_time = time.time() - start_time
    print(f"[MP3 Decoder] Complete: {decode_count} decodes, {total_input_bytes} -> {total_output_bytes} bytes in {total_time:.3f}s")


def mp3_chunks_to_pcm_buffered(chunks, buffer_duration_ms=500):
    """
    Alternative implementation that buffers by duration rather than byte count.
    This should provide more consistent audio chunk sizes.
    """
    buffer = io.BytesIO()
    accumulated_audio = None
    target_samples = None

    print(f"[MP3 Decoder Buffered] Starting with {buffer_duration_ms}ms buffer")

    for chunk in chunks:
        if not chunk:
            continue

        buffer.write(chunk)

        # Try to decode current buffer
        buffer.seek(0)
        try:
            audio = AudioSegment.from_file(buffer, format="mp3")

            # Initialize target on first successful decode
            if target_samples is None:
                target_samples = int(audio.frame_rate * buffer_duration_ms / 1000)
                print(f"[MP3 Decoder Buffered] Target samples per chunk: {target_samples} (rate: {audio.frame_rate}Hz)")

            # Accumulate audio
            if accumulated_audio is None:
                accumulated_audio = audio
            else:
                accumulated_audio += audio

            # Yield chunks when we have enough
            while len(accumulated_audio) >= target_samples:
                chunk_audio = accumulated_audio[:target_samples]
                accumulated_audio = accumulated_audio[target_samples:]
                yield chunk_audio.raw_data

            # Reset buffer
            buffer = io.BytesIO()

        except Exception as e:
            # Continue buffering
            buffer.seek(0, io.SEEK_END)

    # Flush remaining audio
    if accumulated_audio and len(accumulated_audio) > 0:
        yield accumulated_audio.raw_data
        print(f"[MP3 Decoder Buffered] Flushed final {len(accumulated_audio)} samples")
