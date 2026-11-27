"""Offline image-based prioritization for the bounded ArtCraft edit policy."""
import time
from pathlib import Path

from PIL import Image


MODEL_ID = "smolvlm2-500m-artcraft"
MODEL_DIR = Path("/vision-cache/materialized") / MODEL_ID

LABELS = {
    "color": "Change the accent fill color to match the reference swatch or requested color.",
    "position": "Move the accent to the requested position.",
    "stroke": "Correct the outline width and color.",
}


class VisionReviewer:
    def __init__(self):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        if not MODEL_DIR.is_dir():
            raise ValueError("The allowlisted ArtCraft visual model has not been staged")
        self.torch = torch
        torch.set_num_threads(2)
        self.processor = AutoProcessor.from_pretrained(
            MODEL_DIR, local_files_only=True, trust_remote_code=False,
        )
        self.model = AutoModelForImageTextToText.from_pretrained(
            MODEL_DIR, local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=torch.float32,
        ).eval()

    def choose(self, paths, prompt, options):
        started = time.monotonic()
        images = []
        for path in paths:
            with Image.open(path) as source:
                image = source.convert("RGBA")
                canvas = Image.new("RGB", image.size, "#d8d8d8")
                canvas.paste(image, mask=image.getchannel("A"))
                canvas.thumbnail((384, 384), Image.Resampling.LANCZOS)
                images.append(canvas)
        labels = list("ABC")[:len(options)]
        text = prompt + "\nChoose one letter only.\n" + "\n".join(
            f"{label}. {description}" for label, description in zip(labels, options)
        )
        messages = [{"role": "user", "content": [
            *[{"type": "image"} for _ in images], {"type": "text", "text": text},
        ]}]
        template = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        inputs = self.processor(text=template, images=images, return_tensors="pt")
        with self.torch.inference_mode():
            logits = self.model(**inputs, use_cache=False).logits[0, -1]
        scores = []
        for label in labels:
            alternatives = [self.processor.tokenizer.encode(prefix + label, add_special_tokens=False)
                            for prefix in ("", " ")]
            choices = [tokens[0] for tokens in alternatives if len(tokens) == 1]
            if not choices:
                raise ValueError(f"Model tokenizer has no single token for option {label}")
            scores.append(max(float(logits[token]) for token in choices))
        winner = max(range(len(scores)), key=scores.__getitem__)
        return {"index": winner, "logits": dict(zip(labels, scores)), "model": MODEL_ID,
                "seconds": round(time.monotonic() - started, 2)}


def prepare():
    from .allowlist import Allowlist
    from .fetch import materialize_dir

    entry = Allowlist.load().require_model(MODEL_ID, {"evaluator"})
    print(materialize_dir(entry))


if __name__ == "__main__":
    prepare()
