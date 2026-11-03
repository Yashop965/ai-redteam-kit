"""factloop: factuality red-team loop built on Inspect AI.

Layered design (works with or without a model API key):
  * author  - auto-verify each candidate's golden against 2+ text sources,
              score how "buried" it is, rank, emit paste-ready form blocks.
  * grade   - score a model answer you pasted back from Google Search Mode.
  * run     - (optional, needs a key/local) drive a web-research agent on
              Inspect to confirm a failure automatically.
"""
__version__ = "0.1.0"
