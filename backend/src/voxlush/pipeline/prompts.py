"""The same primitive contract is used by author, refinement and repair."""
import ast
import base64
import hashlib
import json
from pathlib import Path
from voxlush.voxel.adapter import primitive_contract
from voxlush.core.files import digest

PROMPT_VERSION = "voxlush.prompt.v1"
RUBRIC_VERSION = "voxlush.visual.v1"
RUBRIC_TEXT = "Inspect actual multi-view images for coherent structure/landforms, usable spatial composition, visible design focus and defects. Do not infer requested tags without evidence. Return JSON only: verdict=pass/fail/gray, issues=[concrete visible defects], observed_tags=[{tag,evidence,confidence}]."
RUBRIC_HASH = hashlib.sha256((RUBRIC_VERSION + "\0" + RUBRIC_TEXT).encode()).hexdigest()

def extract_source(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0] not in ("```python","```py","```") or lines[-1] != "```" or any(line.startswith("```") for line in lines[1:-1]):
            raise ValueError("expected exactly one complete Python fence")
        text = "\n".join(lines[1:-1])
    if not text or len(text.encode())>600000:
        raise ValueError("source size limit or empty source")
    ast.parse(text)
    return text+"\n"

def author_messages(task: dict,source: str | None = None,feedback: dict | None = None,refine=False):
    system = "Independently design and code this voxel asset. Use free Python functions and loops with the provided low-level runtime. Never reuse a fixed building template.\n"+primitive_contract()
    instruction = {"task":task,"phase": "refinement" if refine else task.get("phase","final"),
        "output":"Return exactly one complete Python code block; include literal design metadata. No prose outside the block."}
    if task.get("phase") == "skeleton":
        instruction["stage_requirements"] = "Free-form massing, access, major structure, voids and circulation; preserve freedom for detail refinement."
    if source:
        instruction["current_authored_source"] = source
    if feedback:
        instruction["current_evidence"] = feedback
    return [{"role":"system","content":system},{"role":"user","content":json.dumps(instruction,ensure_ascii=False)}]

def review_messages(task: dict,build_dir: Path):
    images = [build_dir/"previews"/f"view_{v}.webp" for v in ("a","b")]
    evidence = {"schema_version":RUBRIC_VERSION,"task":task,
        "geometry":json.loads((build_dir/"geometry.json").read_text()),
        "rubric":RUBRIC_TEXT}
    content = [{"type":"text","text":json.dumps(evidence,ensure_ascii=False)}]
    for image in images:
        content.append({"type":"image_url","image_url":{"url":"data:image/webp;base64,"+base64.b64encode(image.read_bytes()).decode()}})
    return [{"role":"system","content":"You are the independent visual assessor. Evaluate only submitted images and immutable quality contract; never invent human calibration results."},{"role":"user","content":content}], [digest(p) for p in images]

def parse_review(content,geometry_hash,image_hashes,qualified=False):
    text = content.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    value = json.loads(text)
    if value.get("verdict") not in ("pass","fail","gray") or not isinstance(value.get("issues"),list):
        raise ValueError("invalid review verdict/issues")
    tags = value.get("observed_tags",[])
    if not isinstance(tags,list) or any(not isinstance(t,dict) or not isinstance(t.get("tag"),str) or not t.get("evidence") or not isinstance(t.get("confidence"),(int,float)) or not 0<=t["confidence"]<=1 for t in tags):
        raise ValueError("observed tags require concrete evidence and confidence")
    return {**value,"status":value["verdict"],"passed":value["verdict"]=="pass",
        "input_voxel_sha256":geometry_hash,"image_sha256":image_hashes,"evidence_kind":"live_model",
        "profile_qualified":qualified,"rubric_version":RUBRIC_VERSION,"rubric_hash":RUBRIC_HASH,
        "observed_tags":[{**t,"source":"visual_review","evidence_ref":"review.json"} for t in tags]}
