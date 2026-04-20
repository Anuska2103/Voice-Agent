"""
Run the LiveKit Voice Agent
This is the ONLY file you need to run: python run.py
"""

import sys
from livekit.agents import cli, WorkerOptions
from logger import setup_logging, get_logger

setup_logging()
LOGGER = get_logger(__name__)

# Import the entrypoint
from agent import entrypoint


def main():
    """Run the voice agent"""
    LOGGER.info("Starting LiveKit voice agent")
    
    # Run the LiveKit agent
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            
        )
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        LOGGER.info("Agent stopped by user")
        sys.exit(0)
    except Exception as e:
        LOGGER.exception("Fatal error while running agent: %s", e)
        sys.exit(1)