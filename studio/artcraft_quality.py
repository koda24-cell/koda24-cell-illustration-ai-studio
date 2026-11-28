"""Image-guided ArtCraft edits for explicitly measurable color and position goals."""
import colorsys
import json
from statistics import median

from PIL import Image, ImageChops, ImageColor

from .evaluate import windowed_ssim
from .artcraft_vision import LABELS, VisionReviewer


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
    target = ImageColor.getrgb(goal["rgb"]) if "rgb" in goal else None
    reference = None
    if "reference" in goal:
        # The runner prepares this image before opening the document in MCP.
        path = output / "reference.png"
        with Image.open(path) as image:
            reference = image.convert("RGB")
        target = sample(path, goal["reference"]["sample"])
    thresholds = {"color": 3, "position": 3, "stroke": 0.25}
    reviewer = VisionReviewer() if goal.get("vision_review") else None
    intent = goal.get("intent", "Match the reference color and requested layout.")
    context_images = [path] if reference is not None else []

    def met(errors):
        return all(value <= thresholds[issue] for issue, value in errors.items())

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
        if reference is not None:
            report["derived_target_rgb"] = list(target)
            report["reference_preview"] = "reference.png"

    def save_report():
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(checkpoint)

    async def assess(filename):
        raw = await call(inspect_tool, {})
        doc = json.loads(next(item["text"] for item in raw["content"] if item["type"] == "text"))
        measured = {}
        if target is not None:
            measured["rgb"] = sample(output / filename, goal["sample"])
        if reference is not None:
            with Image.open(output / filename) as image:
                crop = image.convert("RGB").crop(goal["sample"])
                expected = reference.crop(goal["reference"]["sample"])
                measured["reference_ssim"] = round(windowed_ssim(crop, expected), 4)
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
        if target is not None:
            result["color"] = distance(measured["rgb"], target)
        if "position" in goal:
            bounds = measured["object"]["bounds"]
            result["position"] = distance((bounds["x"], bounds["y"]), goal["position"])
        if "stroke" in goal:
            result["stroke"] = abs(measured["object"]["strokeWidth"] - goal["stroke"]["width"])
        return result

    if reviewer is not None:
        report["vision_model_load_seconds"] = reviewer.load_seconds
    before = await assess(report["best_preview"])
    save_report()
    blocked = {entry["issue"] for entry in report["history"] if not entry["accepted"]}
    for number in range(len(report["history"]) + 1, 4):
        errors = score(before)
        issues = [issue for issue, value in errors.items() if value > thresholds[issue] and issue not in blocked]
        if not issues:
            report["stop"] = "target_met" if met(errors) else "stalled"
            break
        priority = None
        if reviewer is not None and len(issues) > 1:
            priority = reviewer.choose([output / report["best_preview"], *context_images],
                                       f"First image is the current design. A second image, if supplied, is a reference swatch. "
                                       f"Design intent: {intent} Which edit should be performed next?",
                                       [LABELS[item] for item in issues])
            issue = issues[priority["index"]]
            priority["options"] = issues
        else:
            issue = max(issues, key=lambda item: errors[item] / thresholds[item])
        if issue == "position":
            obj = before["object"]
            bounds = obj["bounds"]
            tool, args = "run_command", {"command": "object.move", "params": {
                "ids": [obj["id"]], "dx": goal["position"][0] - bounds["x"],
                "dy": goal["position"][1] - bounds["y"],
            }}
        elif issue == "stroke":
            tool, args = "set_paint", {"ids": [before["object"]["id"]],
                                      "stroke": goal["stroke"]["color"],
                                      "strokeWidth": goal["stroke"]["width"]}
        elif photo:
            source = colorsys.rgb_to_hsv(*(value / 255 for value in before["rgb"]))
            desired = colorsys.rgb_to_hsv(*(value / 255 for value in target))
            tool, args = "command_run", {"id": "layer.newAdjustmentLayer.hueSaturation", "params": {
                "hue": round(((desired[0] - source[0] + 0.5) % 1 - 0.5) * 360),
                "saturation": round((desired[1] - source[1]) * 100),
                "lightness": round((desired[2] - source[2]) * 100),
            }}
        else:
            tool, args = "set_paint", {"ids": [before["object"]["id"]], "fill": "#%02x%02x%02x" % tuple(round(value) for value in target)}
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
        if priority is not None:
            report["history"][-1]["vision_priority"] = priority
        if reviewer is not None:
            review = reviewer.choose([output / report["best_preview"], output / preview, *context_images],
                                     f"Compare the first two designs against the intent: {intent} "
                                     "If there is a third image, it is the reference color swatch. Which design better meets the intent?",
                                     ["The first design", "The second design"])
            report["history"][-1]["vision_comparison"] = review
        if reference is not None:
            report["history"][-1]["reference_ssim"] = {
                "before": before["reference_ssim"], "after": after["reference_ssim"],
            }
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
        report["stop"] = "target_met" if met(score(before)) else "iteration_limit"
    save_report()
    return report
