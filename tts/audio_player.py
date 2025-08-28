import pyaudio
import time

class StreamingAudioPlayer:
    """
    Plays PCM audio data from a generator of audio chunks using PyAudio.
    Intended for use with streaming TTS outputs (e.g., ElevenLabs, Polly PCM).
    """

    def __init__(self, sample_rate=44100, channels=1, format=pyaudio.paInt16, chunk_size=8192):
        """
        :param sample_rate: Audio sample rate (Hz).
        :param channels: Number of audio channels.
        :param format: PyAudio format (e.g., pyaudio.paInt16 for 16-bit PCM).
        :param chunk_size: Number of bytes per write to the audio stream (increased for smoother playback).
        """
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.chunk_size = chunk_size
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.debug = True  # Enable debugging by default

    def play(self, audio_chunks):
        """
        Plays audio chunks (bytes) as they arrive from the generator.
        :param audio_chunks: Generator or iterable yielding PCM audio bytes.
        """
        chunk_count = 0
        total_bytes = 0
        start_time = time.time()

        if self.debug:
            print(f"[AudioPlayer] Starting playback (rate={self.sample_rate}, channels={self.channels}, buffer={self.chunk_size})")

        self.stream = self.p.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            output=True,
            frames_per_buffer=self.chunk_size,
            # Add some buffering to help with choppy playback
            stream_callback=None
        )

        try:
            for chunk in audio_chunks:
                if chunk:
                    chunk_start = time.time()
                    self.stream.write(chunk)
                    write_time = time.time() - chunk_start

                    chunk_count += 1
                    total_bytes += len(chunk)

                    if self.debug and write_time > 0.01:  # Log slow writes
                        print(f"[AudioPlayer] Chunk #{chunk_count}: {len(chunk)} bytes, write took {write_time:.3f}s")

        except Exception as e:
            print(f"[AudioPlayer] Playback error: {e}")
            raise
        finally:
            total_time = time.time() - start_time
            if self.debug:
                print(f"[AudioPlayer] Playback complete: {chunk_count} chunks, {total_bytes} bytes in {total_time:.3f}s")

            self.stream.stop_stream()
            self.stream.close()
            self.p.terminate()
