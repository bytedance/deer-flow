from langchain_core.tools import BaseTool

class _PendingGoogleSpeechTool(BaseTool):
    name: str = "google_speech"
    description: str = "Stub: converts text to speech with Google Gemini-TTS (to be implemented)."

    def _run(self, *args, **kwargs):
        raise NotImplementedError("google_speech tool not finished yet.")

google_speech_tool = _PendingGoogleSpeechTool()
