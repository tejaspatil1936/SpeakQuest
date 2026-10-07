"""SpeakQuest analysis engine.

Importing the top-level package must stay cheap: the API Lambda zip ships
``speakquest.contracts`` and ``speakquest.errors`` without numpy/scipy, so
nothing heavy is imported here.
"""

__version__ = "0.1.0"
