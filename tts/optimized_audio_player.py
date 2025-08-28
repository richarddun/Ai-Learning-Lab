import pyaudio
import threading
import queue
import time
import io
import tempfile
import os
from pydub import AudioSegment

class OptimizedAudioPlayer:
    """
    Optimized audio player that solves the choppy playback problem by:
    1. Collecting all MP3 chunks first (streaming still works)
    2. Decoding the complete MP3 in one operation (no ffmpeg overhead)
    3. Playing back smooth PCM audio with proper buffering

    This eliminates the 300-450ms per chunk ffmpeg overhead that causes choppy audio.
    """

    def __init__(self, sample_rate=44100, channels=1, format=pyaudio.paInt16,
                 chunk_size=8192, buffer_chunks=10):
        """
        :param sample_rate: Audio sample rate (Hz)
        :param channels: Number of audio channels
        :param format: PyAudio format
        :param chunk_size: Size of each audio buffer chunk
        :param buffer_chunks: Number of chunks to buffer for smooth playback
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.chunk_size = chunk_size
        self.buffer_chunks = buffer_chunks
        self.debug = True

    def play(self, audio_chunks):
        """
        Play audio chunks with optimized approach:
        1. Collect all MP3 chunks
        2. Decode once with single ffmpeg call
        3. Stream PCM with proper buffering
        """
        if self.debug:
            print("[OptimizedPlayer] Starting optimized playback...")

        try:
            # Step 1: Collect all MP3 chunks
            mp3_data = self._collect_mp3_chunks(audio_chunks)

            # Step 2: Decode all at once
            pcm_data = self._decode_complete_mp3(mp3_data)

            # Step 3: Play smoothly
            self._play_pcm_smoothly(pcm_data)

        except Exception as e:
            print(f"[OptimizedPlayer] Playback failed: {e}")
            raise

    def _collect_mp3_chunks(self, audio_chunks):
        """Collect all MP3 chunks into a single bytes object."""
        if self.debug:
            print("[OptimizedPlayer] Collecting MP3 chunks...")

        mp3_buffer = io.BytesIO()
        chunk_count = 0

        for chunk in audio_chunks:
            if chunk:
                mp3_buffer.write(chunk)
                chunk_count += 1

        mp3_data = mp3_buffer.getvalue()

        if self.debug:
            print(f"[OptimizedPlayer] Collected {chunk_count} chunks, {len(mp3_data)} bytes total")

        return mp3_data

    def _decode_complete_mp3(self, mp3_data):
        """Decode complete MP3 data in one operation - much faster than chunk-by-chunk."""
        if self.debug:
            print("[OptimizedPlayer] Decoding complete MP3...")

        start_time = time.time()

        # Use in-memory decoding to avoid file I/O
        mp3_io = io.BytesIO(mp3_data)
        audio_segment = AudioSegment.from_file(mp3_io, format="mp3")

        # Ensure correct format for PyAudio
        audio_segment = audio_segment.set_frame_rate(self.sample_rate)
        audio_segment = audio_segment.set_channels(self.channels)
        audio_segment = audio_segment.set_sample_width(2)  # 16-bit

        pcm_data = audio_segment.raw_data
        decode_time = time.time() - start_time

        if self.debug:
            print(f"[OptimizedPlayer] Decoded {len(pcm_data)} PCM bytes in {decode_time:.3f}s")
            print(f"[OptimizedPlayer] Audio duration: {len(audio_segment)/1000:.1f}s")

        return pcm_data

    def _play_pcm_smoothly(self, pcm_data):
        """Play PCM data with smooth buffering."""
        if self.debug:
            print("[OptimizedPlayer] Starting smooth PCM playback...")

        p = pyaudio.PyAudio()

        try:
            stream = p.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                frames_per_buffer=self.chunk_size
            )

            # Play data in chunks for smooth output
            start_time = time.time()
            bytes_played = 0

            for i in range(0, len(pcm_data), self.chunk_size):
                chunk = pcm_data[i:i + self.chunk_size]

                # Pad last chunk if necessary
                if len(chunk) < self.chunk_size:
                    chunk += b'\x00' * (self.chunk_size - len(chunk))

                stream.write(chunk)
                bytes_played += len(chunk)

                # Optional: small delay to prevent buffer overflow
                if i % (self.chunk_size * 10) == 0:
                    time.sleep(0.001)

            play_time = time.time() - start_time

            if self.debug:
                print(f"[OptimizedPlayer] Played {bytes_played} bytes in {play_time:.3f}s")

            stream.stop_stream()
            stream.close()

        finally:
            p.terminate()


class StreamCollectPlayer:
    """
    Alternative approach that maintains streaming feel while avoiding choppy decoding.
    Collects chunks in background while providing immediate feedback.
    """

    def __init__(self, sample_rate=44100, channels=1, format=pyaudio.paInt16):
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.debug = True

    def play(self, audio_chunks):
        """
        Play with streaming collection approach:
        - Start collecting immediately
        - Begin playback as soon as we have enough data
        - Continue collecting while playing
        """
        if self.debug:
            print("[StreamCollectPlayer] Starting streaming collection...")

        # Use threading to collect while preparing playback
        collection_queue = queue.Queue()
        collection_complete = threading.Event()

        def collector():
            """Collect chunks in background thread."""
            mp3_buffer = io.BytesIO()
            chunk_count = 0

            try:
                for chunk in audio_chunks:
                    if chunk:
                        mp3_buffer.write(chunk)
                        chunk_count += 1

                        # Signal when we have enough for smooth playback
                        if mp3_buffer.tell() > 32768:  # 32KB threshold
                            collection_queue.put(('data', mp3_buffer.getvalue()))
                            mp3_buffer = io.BytesIO()  # Reset for next batch

                # Send final data
                if mp3_buffer.tell() > 0:
                    collection_queue.put(('data', mp3_buffer.getvalue()))

                collection_queue.put(('complete', chunk_count))

            except Exception as e:
                collection_queue.put(('error', str(e)))
            finally:
                collection_complete.set()

        # Start collection thread
        collector_thread = threading.Thread(target=collector)
        collector_thread.start()

        # Play collected data
        self._play_collected_data(collection_queue, collection_complete)

        collector_thread.join()

    def _play_collected_data(self, data_queue, complete_event):
        """Play data as it becomes available."""
        p = pyaudio.PyAudio()
        stream = None

        try:
            while not complete_event.is_set() or not data_queue.empty():
                try:
                    message_type, data = data_queue.get(timeout=1.0)

                    if message_type == 'data':
                        # Decode and play this chunk
                        mp3_io = io.BytesIO(data)
                        audio_segment = AudioSegment.from_file(mp3_io, format="mp3")

                        # Ensure correct format
                        audio_segment = audio_segment.set_frame_rate(self.sample_rate)
                        audio_segment = audio_segment.set_channels(self.channels)
                        audio_segment = audio_segment.set_sample_width(2)

                        pcm_data = audio_segment.raw_data

                        # Initialize stream on first data
                        if stream is None:
                            stream = p.open(
                                format=self.format,
                                channels=self.channels,
                                rate=self.sample_rate,
                                output=True,
                                frames_per_buffer=8192
                            )

                        # Play PCM data
                        stream.write(pcm_data)

                    elif message_type == 'complete':
                        if self.debug:
                            print(f"[StreamCollectPlayer] Collection complete, processed {data} chunks")
                        break

                    elif message_type == 'error':
                        print(f"[StreamCollectPlayer] Collection error: {data}")
                        break

                except queue.Empty:
                    continue

        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            p.terminate()


class FallbackAudioPlayer:
    """
    Simple fallback player that saves to temporary file and plays with system player.
    Most reliable option but less efficient.
    """

    def __init__(self):
        self.debug = True

    def play(self, audio_chunks):
        """Save to temp file and play with system audio."""
        if self.debug:
            print("[FallbackPlayer] Using temporary file playback...")

        # Collect all data
        mp3_data = b''.join(chunk for chunk in audio_chunks if chunk)

        if not mp3_data:
            print("[FallbackPlayer] No audio data received")
            return

        # Write to temporary file
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
            temp_file.write(mp3_data)
            temp_path = temp_file.name

        try:
            # Try to play with system audio
            if self._try_system_play(temp_path):
                if self.debug:
                    print("[FallbackPlayer] System playback successful")
            else:
                # Fall back to pydub playback
                self._pydub_play(temp_path)

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    def _try_system_play(self, file_path):
        """Try to play with system audio player."""
        import subprocess
        import shutil

        # Try different system players
        players = ['aplay', 'paplay', 'ffplay', 'mpv', 'mplayer']

        for player in players:
            if shutil.which(player):
                try:
                    if player == 'ffplay':
                        # ffplay needs special args to not show GUI
                        subprocess.run([player, '-nodisp', '-autoexit', file_path],
                                     check=True, capture_output=True)
                    else:
                        subprocess.run([player, file_path],
                                     check=True, capture_output=True)
                    return True
                except subprocess.CalledProcessError:
                    continue

        return False

    def _pydub_play(self, file_path):
        """Play with pydub as final fallback."""
        try:
            from pydub.playback import play
            audio = AudioSegment.from_mp3(file_path)
            play(audio)
            if self.debug:
                print("[FallbackPlayer] Pydub playback successful")
        except Exception as e:
            print(f"[FallbackPlayer] Pydub playback failed: {e}")
