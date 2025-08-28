from abc import ABC, abstractmethod
from typing import List, Any

class BaseTTSClient(ABC):
    """
    Abstract base class for TTS clients.
    """

    from typing import Generator

    @abstractmethod
    def stream(self, text, voice_id, **kwargs) -> Generator[bytes, None, None]:
        """
        Yields audio chunks (bytes). For non-streaming providers, yields the full audio at once.
        :param text: Text to synthesize.
        :param voice_id: Voice identifier.
        :param kwargs: Additional provider-specific arguments.
        :return: Generator yielding audio chunks (bytes).
        """
        pass

    @abstractmethod
    def list_voices(self) -> List[Any]:
        """
        Returns a list of available voices for the provider.
        :return: List of voice metadata.
        """
        pass
