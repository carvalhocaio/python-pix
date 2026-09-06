import os

import msgspec

from vessel.application.settlement import DEFAULT_BATCH_SIZE, DEFAULT_IDLE_DELAY

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 3000


class Config(msgspec.Struct, frozen=True):
    host: str
    port: int
    batch_size: int
    idle_delay: float


def load() -> Config:
    env = os.environ
    return Config(
        host=env.get("VESSEL_HOST", DEFAULT_HOST),
        port=int(env.get("VESSEL_PORT", DEFAULT_PORT)),
        batch_size=int(env.get("VESSEL_BATCH_SIZE", DEFAULT_BATCH_SIZE)),
        idle_delay=float(env.get("VESSEL_IDLE_DELAY", DEFAULT_IDLE_DELAY)),
    )
