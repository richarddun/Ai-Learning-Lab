from .audio_player import StreamingAudioPlayer
from .buffered_audio_player import BufferedAudioPlayer, SimpleAudioPlayer
from .optimized_audio_player import OptimizedAudioPlayer, StreamCollectPlayer, FallbackAudioPlayer
from .mp3_decoder import mp3_chunks_to_pcm, mp3_chunks_to_pcm_buffered
from .polly_client import PollyTTSClient
from .elevenlabs_client import ElevenLabsTTSClient

class TTSManager:
    """
    Manages TTS provider selection, streaming, and playback.
    Handles both streaming (ElevenLabs) and non-streaming (Polly) providers.
    """

    def __init__(self, tts_client, is_streaming=True, player_type="optimized"):
        """
        :param tts_client: Instance of BaseTTSClient (Polly or ElevenLabs)
        :param is_streaming: True if provider supports streaming (ElevenLabs), False for full-file (Polly)
        :param player_type: Audio player type ("optimized", "buffered", "simple", "fallback", "original")
        """
        self.tts_client = tts_client
        self.is_streaming = is_streaming
        self.player_type = player_type
        self.player = self._create_player(player_type)

    def _create_player(self, player_type):
        """Create audio player based on type."""
        if player_type == "optimized":
            return OptimizedAudioPlayer(chunk_size=8192, buffer_chunks=10)
        elif player_type == "stream_collect":
            return StreamCollectPlayer()
        elif player_type == "fallback":
            return FallbackAudioPlayer()
        elif player_type == "buffered":
            return BufferedAudioPlayer(chunk_size=16384, buffer_size=5)
        elif player_type == "simple":
            return SimpleAudioPlayer(sample_rate=22050, chunk_size=16384)
        else:  # "original"
            return StreamingAudioPlayer(chunk_size=8192)

    def speak(self, text, voice_id, **kwargs):
        """
        Synthesizes speech and plays it back.
        For streaming providers, audio is played as chunks arrive.
        For non-streaming providers, the full file is played after retrieval.
        :param text: Text to synthesize
        :param voice_id: Voice identifier
        :param kwargs: Additional provider-specific arguments
        """
        try:
            audio_chunks = self.tts_client.stream(text, voice_id, **kwargs)
            if self.is_streaming:
                # ElevenLabs streams MP3
                if self.player_type in ["optimized", "stream_collect", "fallback"]:
                    # These players handle MP3 chunks directly - no pre-decoding needed
                    player = self._create_player(self.player_type)
                    player.play(audio_chunks)
                else:
                    # Legacy players need PCM conversion
                    if self.player_type == "buffered":
                        pcm_chunks = mp3_chunks_to_pcm_buffered(audio_chunks, buffer_duration_ms=500)
                    else:
                        pcm_chunks = mp3_chunks_to_pcm(audio_chunks, min_buffer_size=16384)

                    player = self._create_player(self.player_type)
                    player.play(pcm_chunks)
            else:
                # Polly yields the full audio at once (PCM or MP3)
                audio_data = next(audio_chunks)
                player = self._create_player(self.player_type)
                player.play([audio_data])
        except Exception as e:
            print(f"[TTSManager] Playback failed with {self.player_type} player: {e}")
            # Try fallback chain: optimized -> fallback -> simple
            if self.player_type == "optimized":
                print("[TTSManager] Falling back to fallback player")
                self.player_type = "fallback"
                self.speak(text, voice_id, **kwargs)
            elif self.player_type == "fallback":
                print("[TTSManager] Falling back to simple player")
                self.player_type = "simple"
                self.speak(text, voice_id, **kwargs)
            else:
                print(f"[TTSManager] All fallbacks exhausted, playback failed")

    def list_voices(self):
        """
        Returns a list of available voices from the current provider.
        """
        return self.tts_client.list_voices()

    @staticmethod
    def from_config(provider, **kwargs):
        """
        Factory method to instantiate TTSManager with the correct client and streaming flag.
        :param provider: "polly" or "elevenlabs"
        :param kwargs: Additional arguments for the TTS client (e.g., API keys)
        :return: TTSManager instance
        """
        from dotenv import dotenv_values
        env_vars = dotenv_values('.env')
        # Get player type preference - default to optimized for best performance
        player_type = kwargs.get("player_type", "optimized")

        if provider == "elevenlabs":
            api_key = kwargs.get("api_key") or env_vars.get("ELEVENLABS_API_KEY")
            client = ElevenLabsTTSClient(api_key=api_key, model_id=kwargs.get("model_id", "eleven_multilingual_v2"))
            return TTSManager(client, is_streaming=True, player_type=player_type)
        elif provider == "polly":
            client = PollyTTSClient(
                region_name=kwargs.get("region_name", "us-east-1"),
                aws_access_key_id=kwargs.get("aws_access_key_id"),
                aws_secret_access_key=kwargs.get("aws_secret_access_key"),
            )
            return TTSManager(client, is_streaming=False, player_type=player_type)
        else:
            raise ValueError(f"Unknown TTS provider: {provider}")
