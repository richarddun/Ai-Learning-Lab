from elevenlabs.client import ElevenLabs
from .base import BaseTTSClient

class ElevenLabsTTSClient(BaseTTSClient):
    """
    ElevenLabs TTS client supporting streaming, voice listing, and voice manipulation.
    """

    def __init__(self, api_key=None, model_id="eleven_multilingual_v2"):
        self.client = ElevenLabs(api_key=api_key)
        self.model_id = model_id

    def stream(self, text, voice_id, **kwargs):
        """
        Streams audio chunks (as bytes) from ElevenLabs TTS.
        Yields PCM-encoded MP3 chunks.
        Supports voice manipulation parameters.
        """
        # model_id and other keyword overrides
        model_id = kwargs.get("model_id", self.model_id)

        # Voice settings for character customization
        voice_settings = {
            "stability": kwargs.get("stability", 0.5),
            "similarity_boost": kwargs.get("similarity_boost", 0.8),
            "style": kwargs.get("style", 0.0),
            "use_speaker_boost": kwargs.get("use_speaker_boost", True)
        }

        audio_stream = self.client.text_to_speech.stream(
            text=text,
            voice_id=voice_id,
            model_id=model_id,
            voice_settings=voice_settings
        )
        for chunk in audio_stream:
            if isinstance(chunk, bytes):
                yield chunk

    def list_voices(self):
        """
        Returns a list of available voices (as dicts).
        """
        response = self.client.voices.search()
        return response.voices

    def get_character_voices(self):
        """
        Returns a curated list of character voices perfect for educational use.
        """
        character_voices = {
            "Old Wizard": {
                "voice_id": "Old Wizard",
                "description": "Wise magical mentor",
                "settings": {"stability": 0.7, "style": 0.3, "similarity_boost": 0.9}
            },
            "Android X.Y.Z.": {
                "voice_id": "Android X.Y.Z.",
                "description": "Futuristic AI robot",
                "settings": {"stability": 0.9, "style": 0.1, "similarity_boost": 0.7}
            },
            "Seer Morganna": {
                "voice_id": "Seer Morganna",
                "description": "Mystical fortune teller",
                "settings": {"stability": 0.6, "style": 0.4, "similarity_boost": 0.8}
            },
            "Timmy Medieval": {
                "voice_id": "Timmy",
                "description": "Young energetic character",
                "settings": {"stability": 0.4, "style": 0.2, "similarity_boost": 0.8}
            },
            "Michael Mouse": {
                "voice_id": "Michael Mouse",
                "description": "High-energy comic character",
                "settings": {"stability": 0.3, "style": 0.5, "similarity_boost": 0.9}
            },
            "Evil Witch": {
                "voice_id": "Evil Witch",
                "description": "Dark magical villain",
                "settings": {"stability": 0.5, "style": 0.6, "similarity_boost": 0.8}
            },
            "Kawaii Aerisita": {
                "voice_id": "Kawaii Aerisita",
                "description": "Adorable anime-style voice",
                "settings": {"stability": 0.4, "style": 0.3, "similarity_boost": 0.9}
            },
            "Lutz Laugh": {
                "voice_id": "Lutz Laugh",
                "description": "Chuckling giggly character",
                "settings": {"stability": 0.2, "style": 0.4, "similarity_boost": 0.8}
            }
        }
        return character_voices
