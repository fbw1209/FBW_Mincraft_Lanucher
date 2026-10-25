from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from launcher.config import Config
from launcher.installer import install_version
from launcher.launch import build_launch_plan, offline_uuid
from launcher.version import (
    instance_dir_for_version,
    maven_to_path,
    merge_version,
    required_java_major,
    rules_allow,
)


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


class CoreTests(unittest.TestCase):
    def test_offline_uuid(self) -> None:
        value = offline_uuid("Notch")
        self.assertEqual(len(value), 32)
        self.assertEqual(value[12], "3")
        self.assertIn(value[16], "89ab")
        self.assertEqual(value, offline_uuid("Notch"))
        self.assertNotEqual(value, offline_uuid("notch"))

    def test_maven_path(self) -> None:
        self.assertEqual(
            maven_to_path("org.lwjgl:lwjgl:3.3.1"),
            "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1.jar",
        )
        self.assertEqual(
            maven_to_path("org.lwjgl:lwjgl:3.3.1:natives-windows"),
            "org/lwjgl/lwjgl/3.3.1/lwjgl-3.3.1-natives-windows.jar",
        )

    def test_rules(self) -> None:
        self.assertTrue(rules_allow(None))
        self.assertTrue(rules_allow([{"action": "allow"}]))
        self.assertFalse(rules_allow([{"action": "allow", "os": {"name": "linux"}}]))
        self.assertTrue(
            rules_allow(
                [
                    {"action": "allow"},
                    {"action": "disallow", "os": {"name": "osx"}},
                ]
            )
        )
        self.assertFalse(
            rules_allow([{"action": "allow", "features": {"is_demo_user": True}}])
        )

    def test_instance_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            game_dir = Path(temp)
            version_dir = game_dir / "versions" / "test"
            version_dir.mkdir(parents=True)
            self.assertEqual(instance_dir_for_version(game_dir, "test"), game_dir)
            (version_dir / "mods").mkdir()
            self.assertEqual(instance_dir_for_version(game_dir, "test"), version_dir)

    def test_java_requirement(self) -> None:
        self.assertEqual(required_java_major({"id": "1.8.9"}), 8)
        self.assertEqual(required_java_major({"id": "1.17.1"}), 16)
        self.assertEqual(required_java_major({"id": "1.20.1"}), 17)
        self.assertEqual(required_java_major({"id": "1.21.8"}), 21)
        self.assertEqual(required_java_major({"id": "26.3"}), 21)
        self.assertEqual(required_java_major({"id": "26.3", "javaVersion": {"majorVersion": 25}}), 25)

    def test_merge_version(self) -> None:
        parent = {
            "id": "1.20.1",
            "mainClass": "net.minecraft.client.main.Main",
            "libraries": [{"name": "a:b:1.0"}],
            "arguments": {"game": ["--username", "${auth_player_name}"], "jvm": ["-cp", "${classpath}"]},
        }
        child = {
            "id": "fabric",
            "inheritsFrom": "1.20.1",
            "mainClass": "fabric.Main",
            "libraries": [{"name": "a:b:1.0"}, {"name": "c:d:2.0"}],
            "arguments": {"game": ["--fabric"], "jvm": ["-DFabric=1"]},
        }
        merged = merge_version(parent, child)
        self.assertEqual(merged["mainClass"], "fabric.Main")
        self.assertEqual(merged["_client_jar_id"], "1.20.1")
        self.assertEqual([lib["name"] for lib in merged["libraries"]], ["a:b:1.0", "c:d:2.0"])
        self.assertEqual(merged["arguments"]["game"], ["--username", "${auth_player_name}", "--fabric"])
        self.assertEqual(merged["arguments"]["jvm"], ["-cp", "${classpath}", "-DFabric=1"])

    def test_build_launch_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            game_dir = Path(temp)
            version_dir = game_dir / "versions" / "1.20.1"
            version_dir.mkdir(parents=True)
            library = game_dir / "libraries" / "com" / "example" / "lib" / "1.0" / "lib-1.0.jar"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"library")
            client = version_dir / "1.20.1.jar"
            client.write_bytes(b"client")
            assets_index = game_dir / "assets" / "indexes" / "test.json"
            assets_index.parent.mkdir(parents=True)
            assets_index.write_text("{}", encoding="utf-8")
            version = {
                "id": "1.20.1",
                "type": "release",
                "mainClass": "net.minecraft.client.main.Main",
                "assetIndex": {"id": "test"},
                "javaVersion": {"majorVersion": 17},
                "libraries": [
                    {
                        "name": "com.example:lib:1.0",
                        "downloads": {
                            "artifact": {
                                "path": "com/example/lib/1.0/lib-1.0.jar",
                                "url": "https://example.invalid/lib.jar",
                            }
                        },
                    }
                ],
                "arguments": {
                    "game": [
                        "--username",
                        "${auth_player_name}",
                        "--version",
                        "${version_name}",
                        "--gameDir",
                        "${game_directory}",
                        "--assetsDir",
                        "${assets_root}",
                        "--assetIndex",
                        "${assets_index_name}",
                        "--uuid",
                        "${auth_uuid}",
                        "--accessToken",
                        "${auth_access_token}",
                    ],
                    "jvm": [
                        "-Djava.library.path=${natives_directory}",
                        "-cp",
                        "${classpath}",
                    ],
                },
            }
            (version_dir / "1.20.1.json").write_text(json.dumps(version), encoding="utf-8")
            cfg = Config(username="Tester", game_dir=str(game_dir), max_memory=4096, min_memory=512)
            java = Path("C:/Program Files/Java/jdk-17/bin/java.exe")
            plan = build_launch_plan(game_dir, "1.20.1", cfg, java, 17)
            self.assertEqual(plan.command[0], str(java))
            self.assertIn("-Xmx4096M", plan.command)
            self.assertIn("-Xms512M", plan.command)
            self.assertIn("net.minecraft.client.main.Main", plan.command)
            self.assertIn("--username", plan.command)
            self.assertIn("Tester", plan.command)
            self.assertIn(offline_uuid("Tester"), plan.command)
            classpath = plan.command[plan.command.index("-cp") + 1]
            self.assertIn(str(library), classpath)
            self.assertIn(str(client), classpath)
            self.assertTrue((version_dir / "natives").is_dir())

    def test_install_synthetic_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            game_dir = Path(temp)
            source = Path(temp) / "source"
            source.mkdir()
            client_data = b"fake-client-jar"
            library_data = b"fake-library"
            client_file = source / "client.jar"
            client_file.write_bytes(client_data)
            library_file = source / "lib.jar"
            library_file.write_bytes(library_data)
            version_dir = game_dir / "versions" / "test"
            version_dir.mkdir(parents=True)
            version = {
                "id": "test",
                "type": "release",
                "mainClass": "net.minecraft.client.main.Main",
                "downloads": {
                    "client": {
                        "url": client_file.as_uri(),
                        "size": len(client_data),
                        "sha1": _sha1(client_data),
                    }
                },
                "libraries": [
                    {
                        "name": "com.example:lib:1.0",
                        "downloads": {
                            "artifact": {
                                "path": "com/example/lib/1.0/lib-1.0.jar",
                                "url": library_file.as_uri(),
                                "size": len(library_data),
                                "sha1": _sha1(library_data),
                            }
                        },
                    }
                ],
                "arguments": {"game": [], "jvm": []},
            }
            (version_dir / "test.json").write_text(json.dumps(version), encoding="utf-8")
            progress: list[tuple[int, str]] = []
            installed = install_version(
                game_dir,
                "test",
                source="official",
                progress=lambda percent, text: progress.append((percent, text)),
            )
            self.assertEqual(installed, "test")
            self.assertEqual((version_dir / "test.jar").read_bytes(), client_data)
            self.assertEqual(
                (game_dir / "libraries" / "com" / "example" / "lib" / "1.0" / "lib-1.0.jar").read_bytes(),
                library_data,
            )
            self.assertTrue(progress)
            self.assertEqual(progress[-1][0], 100)


if __name__ == "__main__":
    unittest.main()
