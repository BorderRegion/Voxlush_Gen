"""The same primitive contract is used by author, refinement and repair."""
import ast
import base64
import hashlib
import json
from pathlib import Path
from voxlush.voxel.adapter import primitive_contract, MAX_SOURCE_BYTES
from voxlush.core.files import digest
from voxlush.themes.composition import instruction as composition_instruction, requested_mode, validate_observation

PROMPT_VERSION = "voxlush.prompt.v6"
RUBRIC_VERSION = "voxlush.visual.v4"
RUBRIC_TEXT = """Inspect the actual complementary voxel views. Assess completeness, silhouette and
proportions, structural/detail logic, material harmony, visual hierarchy, style consistency,
theme recognizability and conspicuous repetitive detailing. Passing geometry alone does not
establish visual quality. Fail concrete visible defects such as unfinished masses, incoherent
proportions/materials or missing defining features; do not average away a serious defect.
Use the task's scene contract: landscapes need coherent landforms/ecology, not rooms or roofs;
intentional ruins need coherent damage, not intact walls. Do not invent hidden interior evidence
or claim cross-asset duplication without comparison evidence. Use gray when these views cannot
support a decision, with the specific uncertainty. Do not infer requested tags without evidence.
Return one JSON object only: verdict is a string ('pass', 'fail' or 'gray'); issues is a list of
strings describing concrete visible defects or uncertainties (empty for pass, nonempty otherwise);
observed_tags is a list of objects with tag (string), evidence (nonempty string describing visible
support), and confidence (a JSON number between 0 and 1, e.g. 0.8; never 'high', 'medium' or 'low').
When task.composition_mode is set, also return context_assessment: {observed_mode:
'pure_target'|'light_context'|'contextual'|'environment_rich'|null,
building_focus:'dominant'|'co_primary'|'incidental'|'absent'|'unclear',
extraneous_environment:boolean, evidence:nonempty string, confidence:number 0..1}.
Classify the actual images, not requested labels or declared component categories. Pure means
one main building with necessary contact treatment and functional attachments, not a settlement;
light allows small supporting scenery;
contextual has a moderate surrounding scene; environment_rich has strong landscape storytelling.
Check both views for visual centrality, framing, distracting large terrain/trees/water, and whether
the building is merely incidental. Describe visible context and subject proportion, including
mislabelled environmental components. Pure/light must remain visually dominant, with no extraneous
surroundings; other modes need a recognizable main architectural subject. Context control must not
reward a crude empty box or penalize architectural detail, foundations or functional attachments.
Use null/unclear and gray when the images cannot establish this. Natural tasks use their original
landscape contract and do not require a building context assessment."""
RUBRIC_HASH = hashlib.sha256((RUBRIC_VERSION + "\0" + RUBRIC_TEXT).encode()).hexdigest()

def extract_source(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        fences = [i for i, line in enumerate(lines) if line.startswith("```")]
        if (lines[0] not in ("```python","```py","```") or len(fences) != 2
                or lines[fences[1]].strip() != "```"):
            raise ValueError("expected exactly one complete Python fence")
        # A single leading, explicitly closed block is unambiguous. Preserve its
        # entire program; trailing model commentary is neither code nor a repair.
        text = "\n".join(lines[1:fences[1]])
    if not text or len((text+'\n').encode())>MAX_SOURCE_BYTES:
        raise ValueError("source size limit or empty source")
    ast.parse(text)
    return text+"\n"

def compact_evidence(evidence):
    """A bounded model view; the original diagnostic file remains authoritative."""
    def trim(value, depth=0):
        if depth > 5:
            return '[see full local report]'
        if isinstance(value,str):
            # Tracebacks end with the actionable exception; a prefix-only trim
            # discarded it in live repairs. Retain both context and root cause.
            return value if len(value) <= 600 else value[:260]+'\n...[truncated]...\n'+value[-300:]
        if isinstance(value,list):
            return [trim(item,depth+1) for item in value[:8]]
        if isinstance(value,dict):
            return {k:trim(v,depth+1) for k,v in list(value.items())[:16]}
        return value
    keys = ('error_category','message','violations','issues','errors','canonical_voxel_hash','passed')
    result = {key:trim(evidence[key]) for key in keys if key in evidence}
    # Avoid a long nested component report crowding out the source and contract.
    while len(json.dumps(result,ensure_ascii=False).encode()) > 8000:
        arrays = [v for v in result.values() if isinstance(v,list) and len(v)>1]
        if arrays:
            max(arrays,key=lambda v:len(json.dumps(v))).pop()
        else:
            return {'error_category':str(evidence.get('error_category','geometry_failed'))[:120],
                    'message':json.dumps(result,ensure_ascii=False)[:1800]}
    return result

def author_messages(task: dict,source: str | None = None,feedback: dict | None = None,refine=False):
    system = "Independently design and code this voxel asset. Use free Python functions and loops with the provided low-level runtime. Never reuse a fixed building template.\n"+primitive_contract()
    instruction = {"task":task,"phase": "refinement" if refine else task.get("phase","final"),
        "output":"Return exactly one complete Python code block; include literal design metadata. No prose outside the block."}
    if task.get("phase") == "skeleton":
        instruction["stage_requirements"] = "Free-form massing, access, major structure, voids and circulation; preserve freedom for detail refinement."
    context = composition_instruction(task)
    if context:
        instruction['scene_composition'] = context
    if source:
        instruction["current_authored_source"] = source
    if feedback:
        instruction["current_evidence"] = compact_evidence(feedback)
    return [{"role":"system","content":system},{"role":"user","content":json.dumps(instruction,ensure_ascii=False)}]

def review_messages(task: dict,build_dir: Path):
    images = [build_dir/"previews"/f"view_{v}.webp" for v in ("a","b")]
    evidence = {"schema_version":RUBRIC_VERSION,"task":task,
        "geometry":compact_evidence(json.loads((build_dir/"geometry.json").read_text())),
        "rubric":RUBRIC_TEXT, "scene_composition":composition_instruction(task),
        "context_measurement":json.loads((build_dir/'geometry.json').read_text()).get('evidence',{}).get('composition')}
    content = [{"type":"text","text":json.dumps(evidence,ensure_ascii=False)}]
    for image in images:
        content.append({"type":"image_url","image_url":{"url":"data:image/webp;base64,"+base64.b64encode(image.read_bytes()).decode()}})
    return [{"role":"system","content":"You are the independent visual assessor. Evaluate only submitted images and immutable quality contract; never invent human calibration results."},{"role":"user","content":content}], [digest(p) for p in images]

def parse_review(content,geometry_hash,image_hashes,qualified=False,task=None):
    text = content.strip()
    if text.startswith("```json\n") and text.endswith("\n```"):
        text = text[8:-4]
    value = json.loads(text)
    if not isinstance(value,dict) or value.get("verdict") not in ("pass","fail","gray") or not isinstance(value.get("issues"),list):
        raise ValueError("invalid review verdict/issues")
    if any(not isinstance(issue,str) or not issue.strip() for issue in value['issues']):
        raise ValueError("review issues require concrete text")
    if (value['verdict'] == 'pass') != (not value['issues']):
        raise ValueError("review verdict and issues disagree")
    tags = value.get("observed_tags",[])
    if not isinstance(tags,list) or any(not isinstance(t,dict) or not isinstance(t.get("tag"),str) or not t['tag'].strip() or not isinstance(t.get('evidence'),str) or not t['evidence'].strip() or type(t.get("confidence")) not in (int,float) or not 0<=t["confidence"]<=1 for t in tags):
        raise ValueError("observed tags require concrete evidence and confidence")
    mode = requested_mode(task or {})
    if mode:
        observation = validate_observation(mode,value.get('context_assessment'))
        meets = observation['meets_requested']
        value['context_assessment'] = observation
        if meets is not True and value['verdict'] == 'pass':
            value['verdict'] = 'gray' if meets is None else 'fail'
            value['issues'] = ['Composition '+ ('uncertain: ' if meets is None else 'mismatch: ') + observation['evidence']]
    return {**value,"status":value["verdict"],"passed":value["verdict"]=="pass",
        "input_voxel_sha256":geometry_hash,"image_sha256":image_hashes,"evidence_kind":"live_model",
        "profile_qualified":qualified,"rubric_version":RUBRIC_VERSION,"rubric_hash":RUBRIC_HASH,
        "observed_tags":[{**t,"source":"visual_review","evidence_ref":"review.json"} for t in tags]}
