"""Run a scoped ArtCraft MCP batch or prepare a pinned upstream release."""
import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops

from .artcraft_quality import improve
from .scan import clamscan, require_clamav, safe_extract
from .util import ID_RE, now_iso, sha256_file


ROOT = Path(__file__).resolve().parents[1]
ENGINES = json.loads((ROOT / "config/artcraft.json").read_text())


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def prepare(engine, destination, evidence):
    release = ENGINES[engine]
    version = release["version"]
    require_clamav()
    with tempfile.TemporaryDirectory() as temporary:
        name = f"{engine}-{version}-linux-x86_64.tar.gz"
        url = f"https://github.com/storytold/{engine}/releases/download/v{version}/{name}"
        archive = Path(temporary) / name
        urllib.request.urlretrieve(url, archive)
        reports = [clamscan([archive])]
        write_json(evidence, {"url": url, "scans": reports})
        if reports[0]["status"] != "SAFETY_CHECK_OK" or sha256_file(archive) != release["sha256"]:
            raise ValueError("Release scan or SHA256 check failed")
        destination.mkdir()
        safe_extract(archive, destination)
        reports.append(clamscan([destination]))
        write_json(evidence, {"url": url, "scans": reports})
        if reports[1]["status"] != "SAFETY_CHECK_OK":
            raise ValueError("Extracted release scan failed")


class Mcp:
    def __init__(self, process):
        self.process = process
        self.request_id = 0

    async def send(self, method, params=None, reply=True):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if reply:
            self.request_id += 1
            message["id"] = self.request_id
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()
        if not reply:
            return None
        async with asyncio.timeout(45):
            while line := await self.process.stdout.readline():
                response = json.loads(line)
                if response.get("id") != self.request_id:
                    continue
                if "error" in response:
                    raise RuntimeError(response["error"])
                result = response["result"]
                if result.get("isError"):
                    raise RuntimeError(result["content"])
                return result
        raise RuntimeError(f"MCP closed while handling {method}")

    async def catalog(self):
        tools = []
        cursor = None
        while True:
            page = await self.send("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(page["tools"])
            cursor = page.get("nextCursor")
            if not cursor:
                return tools


async def batch(binary, job, inputs, output, resume=False):
    started = time.monotonic()
    cli_version = subprocess.check_output([binary, "--version"], text=True, timeout=15).strip()
    if ENGINES[job["engine"]]["version"] not in cli_version:
        raise ValueError(f"Unexpected CLI version: {cli_version}")
    logs = []
    with (output / "mcp.stderr.log").open("w") as stderr:
        server = await asyncio.create_subprocess_exec(
            binary, "mcp", *ENGINES[job["engine"]]["mcp_args"],
            "--automation-read-root", str(inputs),
            "--automation-read-root", str(output),
            "--automation-write-root", str(output),
            cwd=output, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=stderr, limit=16 * 1024 * 1024,
        )
        client = Mcp(server)
        try:
            init = await client.send("initialize", {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "illustration-ai-studio", "version": "1"},
            })
            await client.send("notifications/initialized", reply=False)
            tools = await client.catalog()
            write_json(output / "tools.json", tools)
            known = {tool["name"] for tool in tools}
            if set(op["name"] for op in job["operations"]) - known:
                raise ValueError("Job requests a tool absent from tools/list")
            async def call(name, arguments):
                op = {"name": name, "arguments": arguments}
                entry = {"operation": op}
                logs.append(entry)
                try:
                    entry["result"] = await client.send("tools/call", op)
                except Exception as error:
                    entry["error"] = str(error)
                    raise
                return entry["result"]

            split = job.get("quality_before", len(job["operations"]))
            if not (resume and (output / "quality.json").exists()):
                for op in job["operations"][:split]:
                    await call(**op)
            if "quality_goal" in job:
                await improve(call, job["engine"], job["quality_goal"], output, resume=resume)
            for op in job["operations"][split:]:
                await call(**op)
        except Exception:
            stderr.flush()
            if (output / "mcp.stderr.log").stat().st_size:
                print((output / "mcp.stderr.log").read_text(errors="replace")[-4096:])
            raise
        finally:
            server.stdin.close()
            try:
                await asyncio.wait_for(server.wait(), 5)
            except TimeoutError:
                server.kill()
                await server.wait()
            write_json(output / "operations.json", logs)
    if server.returncode:
        raise RuntimeError(f"MCP shutdown status {server.returncode}")
    return {"version": cli_version, "mcp": init, "seconds": round(time.monotonic() - started, 2)}


def run(binary, job_path, inputs, output, resume=False):
    job = json.loads(job_path.read_text())
    if job["engine"] not in ENGINES or job["public_test_fixture"] is not True:
        raise ValueError("Use a supported engine and an explicitly public test fixture")
    operations = job["operations"]
    if not 1 <= len(operations) <= 40:
        raise ValueError("Expected 1–40 operations")
    for op in operations:
        if set(op) != {"name", "arguments"} or not isinstance(op["arguments"], dict):
            raise ValueError("Each operation needs a tool name and argument object")
    for name in job["expected"]:
        if Path(name).name != name or name in {"", ".", ".."}:
            raise ValueError("Expected outputs must be plain filenames")
    output.mkdir(exist_ok=resume)
    if job.get("fixture") == "blue-square" and not (output / "before.png").exists():
        Image.new("RGBA", (64, 48), "#204e86").save(output / "before.png")
    evidence = asyncio.run(batch(binary, job, inputs, output, resume))
    files = {}
    for name in job["expected"]:
        path = output / name
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing output: {name}")
        item = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        if path.suffix == ".png":
            with Image.open(path) as image:
                image.load()
                item.update(size=image.size, mode=image.mode)
                if image.convert("RGBA").getextrema()[3][1] == 0:
                    raise ValueError(f"Fully transparent output: {name}")
        if path.suffix == ".svg" and ET.parse(path).getroot().tag != "{http://www.w3.org/2000/svg}svg":
            raise ValueError("Invalid SVG root")
        files[name] = item
    with Image.open(output / "after.png") as after, Image.open(output / "reopened.png") as reopened:
        if after.size != reopened.size or ImageChops.difference(after.convert("RGBA"), reopened.convert("RGBA")).getbbox(alpha_only=False):
            raise ValueError("Native save/reopen changed rendered pixels")
        if (output / "before.png").exists():
            with Image.open(output / "before.png") as before:
                if not ImageChops.difference(before.convert("RGBA"), after.convert("RGBA")).getbbox(alpha_only=False):
                    raise ValueError("PhotoCraft output did not change")
    write_json(output / "verification.json", {
        **evidence, "quality": json.loads((output / "quality.json").read_text()) if "quality_goal" in job else None,
        "engine": job["engine"], "outputs": files, "native_roundtrip": True,
        "actions_url": os.environ.get("ARTCRAFT_RUN_URL"), "approval": "pending",
    })



def review(source, destination, run_id):
    """Adapt verified public fixtures to the Studio review site's existing run format."""
    if not ID_RE.fullmatch(run_id):
        raise ValueError("Invalid Studio run ID")
    result = json.loads((source / "verification.json").read_text())
    engine = result["engine"]
    if engine not in ENGINES or result["native_roundtrip"] is not True:
        raise ValueError("Expected a verified ArtCraft fixture")
    destination.mkdir()
    with Image.open(source / "after.png") as after:
        after.load()
        shutil.copyfile(source / "after.png", destination / "after.png")
        comparison = None
        if (source / "before.png").is_file():
            with Image.open(source / "before.png") as before:
                comparison = "comparison.png"
                panel = Image.new("RGBA", (before.width + after.width, max(before.height, after.height)))
                panel.paste(before, (0, 0))
                panel.paste(after, (before.width, 0))
                panel.save(destination / comparison)
    quality = result.get("quality")
    if quality:
        for preview in source.glob("preview-*.png"):
            shutil.copyfile(preview, destination / preview.name)
    operations = json.loads((source / "operations.json").read_text())
    editable = next(name for name in result["outputs"] if name.endswith((".pcraft", ".vectorcraft")))
    shutil.copyfile(source / editable, destination / editable)
    write_json(destination / "run.json", {
        "run_id": run_id, "job_id": engine, "title": f"ArtCraft · {result['version']}",
        "status": "done", "backend": engine, "runtime": "Docker / MCP",
        "publish": True, "created_at": now_iso(), "finished_at": now_iso(),
        "elapsed_min": round(result["seconds"] / 60, 3), "actions_runs": [result["actions_url"]],
    })
    write_json(destination / "state.json", {
        "job": {"operations": [entry["operation"] for entry in operations]},
        "stages": {"edit": {"status": "done", "stop_reason": quality["stop"] if quality else "native roundtrip",
                            "best": {"image": "after.png"}, "comparison": comparison,
                            "rounds": [{"candidates": [{"image": p.name} for p in sorted(destination.glob("preview-*.png"))]}]}},
    })
    write_json(destination / "after.json", {"evaluation": {"note": "Native PNG roundtrip: pixel-identical"}})
    write_json(destination / "artcraft.json", {**result, "editable": editable})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    installation = commands.add_parser("prepare")
    installation.add_argument("engine", choices=ENGINES)
    installation.add_argument("destination", type=Path)
    installation.add_argument("evidence", type=Path)
    execution = commands.add_parser("run")
    execution.add_argument("binary")
    execution.add_argument("job", type=Path)
    execution.add_argument("inputs", type=Path)
    execution.add_argument("output", type=Path)
    execution.add_argument("--resume", action="store_true")
    publication = commands.add_parser("review")
    publication.add_argument("source", type=Path)
    publication.add_argument("destination", type=Path)
    publication.add_argument("run_id")
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.engine, args.destination, args.evidence)
    elif args.action == "review":
        review(args.source, args.destination, args.run_id)
    else:
        run(args.binary, args.job, args.inputs.resolve(), args.output.resolve(), args.resume)


if __name__ == "__main__":
    main()
