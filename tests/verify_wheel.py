"""Run with the Python interpreter of a clean installation of the built wheel."""

from importlib.metadata import distribution
from pathlib import Path


def main() -> None:
    dist = distribution("endstone-creeper-rewind")
    assert dist.version == "0.1.2"
    points = [ep for ep in dist.entry_points if ep.group == "endstone"]
    assert len(points) == 1
    assert points[0].name == "creeper_rewind"
    assert points[0].value == "endstone_creeper_rewind:CreeperRewindPlugin"
    config_path = dist.locate_file("endstone_creeper_rewind/config.toml")
    assert config_path.is_file()
    config = config_path.read_text(encoding="utf-8")
    assert "max-age-seconds = 300" in config
    assert "persist = true" in config
    assert not Path("snapshots.json").exists()
    print("Clean wheel: metadata, Endstone entry point and packaged default config OK")


if __name__ == "__main__":
    main()
