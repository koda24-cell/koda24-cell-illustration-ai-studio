"""Image-guided ArtCraft edits for explicitly measurable color and position goals."""
import colorsys
import json
from pathlib import Path
from statistics import median

from PIL import Image, ImageChops, ImageColor


def sample(path, box):
    with Image.open(path) as image:
        if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
            raise ValueError("Sample lies outside the preview")
        pixels = [pixel[:3] for pixel in image.convert("RGBA").crop(box).getdata() if pixel[3] >= 128]
    if not pixels:
        raise ValueError("Sample contains no opaque pixels")
    return tuple(median(channel) for channel in zip(*pixels))


def distance(actual, desired):
    return sum(abs(a - b) for a, b in zip(actual, desired)) / len(desired)


def protected_equal(original, candidate, boxes):
    with Image.open(original) as before, Image.open(candidate) as after:
        return before.size == after.size and all(
            not ImageChops.difference(before.convert("RGBA").crop(box),
                                       after.convert("RGBA").crop(box)).getbbox(alpha_only=False)
            for box in boxes
        )


def find_object(nodes, name):
    matches = []
    for node in nodes:
        if node.get("name") == name and node.get("kind") != "Layer" and not node.get("locked"):
            matches.append(node)
        matches.extend(find_object(node.get("children", []), name))
    return matches


async def improve(call, engine, goal, output, *, resume=False):
    photo = engine == "photocraft"
    open_tool, save_tool, export_tool = (
        ("doc_open", "doc_save", "doc_export") if photo else ("open_file", "save_file", "export")
    )
    inspect_tool = "doc_inspect" if photo else "inspect_document"
    ext = "pcraft" if photo else "vectorcraft"
    checkpoint = output / "quality.json"

    async def file_op(tool, filename):
        await call(tool, {"path": filename})

    if resume and checkpoint.exists():
        report = json.loads(checkpoint.read_text())
        await file_op(open_tool, report["best_native"])
    else:
        await file_op(export_tool, "preview-00.png")
        await file_op(save_tool, f"checkpoint-00.{ext}")
        report = {"goal": goal, "history": [], "best_preview": "preview-00.png",
                  "best_native": f"checkpoint-00.{ext}"}

    def save_report():
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(checkpoint)

    async def assess(filename):
        raw = await call(inspect_tool, {})
        doc = json.loads(next(item["text"] for item in raw["content"] if item["type"] == "text"))
        measured = {}
        if "rgb" in goal:
            measured["rgb"] = sample(output / filename, goal["sample"])
        if not photo:
            matches = find_object(doc.get("layers", []), goal["object"])
            if len(matches) != 1:
                raise ValueError("Expected one unlocked target object")
            measured["object"] = matches[0]
        else:
            measured["layers"] = len(doc["layers"])
        return measured

    def score(measured):
        result = {}
        if "rgb" in goal:
            result["color"] = distance(measured["rgb"], ImageColor.getrgb(goal["rgb"]))
        if "position" in goal:
            bounds = measured["object"]["bounds"]
            result["position"] = distance((bounds["x"], bounds["y"]), goal["position"])
        return result

    before = await assess(report["best_preview"])
    save_report()
    blocked = {entry["issue"] for entry in report["history"] if not entry["accepted"]}
    for number in range(len(report["history"]) + 1, 4):
        errors = score(before)
        issues = [issue for issue, value in errors.items() if value > 3 and issue not in blocked]
        if not issues:
            report["stop"] = "target_met" if max(errors.values()) <= 3 else "stalled"
            break
        issue = max(issues, key=errors.get)
        if issue == "position":
            obj = before["object"]
            bounds = obj["bounds"]
            tool, args = "run_command", {"command": "object.move", "params": {
                "ids": [obj["id"]], "dx": goal["position"][0] - bounds["x"],
                "dy": goal["position"][1] - bounds["y"],
            }}
        elif photo:
            source = colorsys.rgb_to_hsv(*(value / 255 for value in before["rgb"]))
            desired = colorsys.rgb_to_hsv(*(value / 255 for value in ImageColor.getrgb(goal["rgb"])))
            tool, args = "command_run", {"id": "layer.newAdjustmentLayer.hueSaturation", "params": {
                "hue": round(((desired[0] - source[0] + 0.5) % 1 - 0.5) * 360),
                "saturation": round((desired[1] - source[1]) * 100),
                "lightness": round((desired[2] - source[2]) * 100),
            }}
        else:
            tool, args = "set_paint", {"ids": [before["object"]["id"]], "fill": goal["rgb"]}
        await call(tool, args)
        preview = f"preview-{number:02}.png"
        await file_op(export_tool, preview)
        after = await assess(preview)
        next_errors = score(after)
        protected = protected_equal(output / "preview-00.png", output / preview, goal.get("protected", []))
        accepted = protected and sum(next_errors.values()) < sum(errors.values()) - 0.01
        report["history"].append({
            "issue": issue, "before": errors, "after": next_errors, "protected": protected,
            "tool": tool, "arguments": args, "preview": preview, "accepted": accepted,
        })
        if accepted:
            native = f"checkpoint-{number:02}.{ext}"
            await file_op(save_tool, native)
            report.update(best_preview=preview, best_native=native)
            before = after
        else:
            blocked.add(issue)
            await file_op(open_tool, report["best_native"])
        save_report()
    else:
        report["stop"] = "target_met" if max(score(before).values()) <= 3 else "iteration_limit"
    save_report()
    return report
