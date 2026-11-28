"""Offline image-based prioritization for the bounded ArtCraft edit policy."""
import json
import time
from pathlib import Path

from PIL import Image, ImageOps


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
        from transformers import AutoImageProcessor, AutoModelForImageTextToText, AutoTokenizer

        started = time.monotonic()
        if not MODEL_DIR.is_dir():
            raise ValueError("The allowlisted ArtCraft visual model has not been staged")
        self.torch = torch
        torch.set_num_threads(2)
        self.tokenizer = AutoTokenizer.from_pretrained(
            MODEL_DIR, local_files_only=True, trust_remote_code=False,
        )
        self.image_processor = AutoImageProcessor.from_pretrained(
            MODEL_DIR, local_files_only=True, trust_remote_code=False,
        )
        self.chat_template = json.loads((MODEL_DIR / "chat_template.json").read_text())["chat_template"]
        image_seq_len = json.loads((MODEL_DIR / "processor_config.json").read_text())["image_seq_len"]
        # SmolVLM's single-image prompt format. No video inputs or video dependencies.
        self.image_prompt = "<fake_token_around_image><global-img>" + "<image>" * image_seq_len + "<fake_token_around_image>"
        self.image_seq_len = image_seq_len
        self.model = AutoModelForImageTextToText.from_pretrained(
            MODEL_DIR, local_files_only=True, trust_remote_code=False,
            use_safetensors=True, dtype=torch.float32,
        ).eval()
        self.load_seconds = round(time.monotonic() - started, 2)

    def choose(self, paths, prompt, options):
        started = time.monotonic()
        images = []
        for path in paths:
            with Image.open(path) as source:
                image = source.convert("RGBA")
                canvas = Image.new("RGB", image.size, "#d8d8d8")
                canvas.paste(image, mask=image.getchannel("A"))
                images.append(ImageOps.pad(canvas, (512, 512), color="#d8d8d8"))
        labels = list("ABC")[:len(options)]
        text = prompt + "\nChoose one letter only.\n" + "\n".join(
            f"{label}. {description}" for label, description in zip(labels, options)
        )
        messages = [{"role": "user", "content": [
            *[{"type": "image"} for _ in images], {"type": "text", "text": text},
        ]}]
        template = self.tokenizer.apply_chat_template(
            messages, chat_template=self.chat_template, add_generation_prompt=True, tokenize=False,
        )
        template = template.replace("<image>", self.image_prompt, len(images))
        text_inputs = self.tokenizer(template, add_special_tokens=False, return_tensors="pt")
        if int((text_inputs["input_ids"] == self.model.config.image_token_id).sum()) != len(images) * self.image_seq_len:
            raise ValueError("SmolVLM image tokens do not match the supplied images")
        image_inputs = self.image_processor(images=[images], return_tensors="pt",
                                            do_image_splitting=False, size={"longest_edge": 512})
        inputs = {**text_inputs, **image_inputs}
        with self.torch.inference_mode():
            logits = self.model(**inputs, use_cache=False).logits[0, -1]
        scores = []
        for label in labels:
            alternatives = [self.tokenizer.encode(prefix + label, add_special_tokens=False)
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
