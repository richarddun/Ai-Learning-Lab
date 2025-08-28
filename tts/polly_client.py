import boto3
from .base import BaseTTSClient

class PollyTTSClient(BaseTTSClient):
    """
    AWS Polly TTS client.
    Only supports non-streaming (full audio file) playback.
    Intended as a fallback when ElevenLabs is unavailable.
    """

    def __init__(self, region_name="us-east-1", aws_access_key_id=None, aws_secret_access_key=None):
        self.client = boto3.client(
            "polly",
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

    def stream(self, text, voice_id, output_format="pcm", **kwargs):
        """
        Synthesizes speech using AWS Polly and yields the entire audio as a single chunk.
        This method matches the interface of ElevenLabsTTSClient.stream for compatibility.
        """
        response = self.client.synthesize_speech(
            Text=text,
            VoiceId=voice_id,
            OutputFormat=output_format,
            **kwargs
        )
        audio_stream = response.get('AudioStream')
        if audio_stream:
            yield audio_stream.read()
        else:
            raise RuntimeError("No AudioStream returned from Polly.")

    def list_voices(self):
        """
        Returns a list of available Polly voices.
        """
        result = self.client.describe_voices()
        return result.get('Voices', [])
